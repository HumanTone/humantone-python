"""Tests for `humantone.errors.parse_response` (§4.7, §4.8, §4.11, §4.14)."""

from __future__ import annotations

import json
from datetime import timezone
from typing import Any

import pytest

from humantone.errors import (
    APIError,
    AuthenticationError,
    DailyLimitExceededError,
    HumanToneError,
    InsufficientCreditsError,
    InvalidRequestError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    parse_response,
)
from humantone.models import AccountInfo, DetectResult, HumanizeResult, OutputFormat


def _b(payload: dict[str, Any] | str | bytes) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_humanize_success_decodes_dto_with_content_to_text_rename() -> None:
    body = {
        "success": True,
        "request_id": "rid-1",
        "content": "humanized text",
        "output_format": "text",
        "credits_used": 3,
    }
    result = parse_response(
        status_code=200,
        body_bytes=_b(body),
        headers={},
        endpoint="humanize",
    )
    assert isinstance(result, HumanizeResult)
    assert result.text == "humanized text"
    assert result.output_format is OutputFormat.TEXT
    assert result.credits_used == 3
    assert result.request_id == "rid-1"


def test_detect_success() -> None:
    result = parse_response(
        status_code=200,
        body_bytes=_b({"success": True, "ai_score": 87}),
        headers={},
        endpoint="detect",
    )
    assert isinstance(result, DetectResult)
    assert result.ai_score == 87


def test_account_success_parses_expires_at_to_utc_datetime() -> None:
    body = {
        "plan": {
            "id": "pro",
            "name": "Pro",
            "max_words": 1500,
            "monthly_credits": 1000,
            "api_access": True,
        },
        "credits": {"trial": 0, "subscription": 820, "extra": 150, "total": 970},
        "subscription": {"active": True, "expires_at": "2026-05-08T00:00:00.000Z"},
    }
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert isinstance(result, AccountInfo)
    assert result.plan.max_words == 1500
    assert result.subscription.expires_at is not None
    assert result.subscription.expires_at.tzinfo is timezone.utc
    assert result.subscription.expires_at.year == 2026


def test_success_without_explicit_success_field_is_treated_as_success() -> None:
    body = {"ai_score": 50}  # no `success` key
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert isinstance(result, DetectResult)


def test_success_with_truthy_non_true_value_is_still_success() -> None:
    """Per §4.8 1c: only strict `is False` triggers error path."""
    body = {"success": 1, "ai_score": 50}
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert isinstance(result, DetectResult)


def test_success_zero_does_not_trigger_error_path() -> None:
    """`0 is False` is False in Python — so success:0 is not a strict failure."""
    body = {"success": 0, "ai_score": 50}
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert isinstance(result, DetectResult)


# ---------------------------------------------------------------------------
# 200 + success:false (§4.8 step 1b)
# ---------------------------------------------------------------------------


def test_detect_daily_limit_raises_daily_limit_exceeded() -> None:
    body = {
        "success": False,
        "error": "Daily usage limit reached. You have used 30 of 30 allowed detections today.",
        "time_to_next_renew": 3600,
    }
    with pytest.raises(DailyLimitExceededError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    e = excinfo.value
    assert e.status_code == 200  # the API quirk
    assert e.time_to_next_renew == 3600
    assert e.error_code == "daily_limit_exceeded"
    assert "Daily usage limit reached" in str(e)


def test_detect_daily_limit_without_time_to_next_renew_field() -> None:
    body = {
        "success": False,
        "error": "Daily usage limit reached. So sorry.",
    }
    with pytest.raises(DailyLimitExceededError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert excinfo.value.time_to_next_renew is None


def test_detect_service_error_raises_api_error_retryable() -> None:
    body = {"success": False}  # no error message
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert excinfo.value.retryable is True
    assert excinfo.value.status_code == 200


def test_humanize_200_success_false_raises_api_error_retryable() -> None:
    """Reserved variant — not currently sent by server but algorithm covers it."""
    body = {"success": False}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert excinfo.value.retryable is True
    assert excinfo.value.status_code == 200


# ---------------------------------------------------------------------------
# 4xx error mapping (§4.7 + §4.11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "message", "expected_cls", "expected_code"),
    [
        # Cross-endpoint 401 messages
        (
            401,
            "Missing or invalid Authorization header",
            AuthenticationError,
            "authentication_error",
        ),
        (401, "Invalid API key format", AuthenticationError, "authentication_error"),
        (401, "Invalid API key", AuthenticationError, "authentication_error"),
        (401, "This API key has been revoked", AuthenticationError, "authentication_error"),
        (401, "User not found", AuthenticationError, "authentication_error"),
        # 403
        (
            403,
            "Your current plan does not include API access. Please upgrade to continue.",
            PermissionError,
            "permission_denied",
        ),
        # 404
        (404, "Not Found", NotFoundError, "not_found"),
        (404, "Plan not found", NotFoundError, "not_found"),
        # 405
        (405, "Method not allowed", InvalidRequestError, "invalid_request"),
        # humanize 400 verbatim messages
        (400, "Invalid JSON body", InvalidRequestError, "invalid_request"),
        (400, "content is required", InvalidRequestError, "invalid_request"),
        (400, "Text must be at least 30 words", InvalidRequestError, "text_too_short"),
        (
            400,
            "Text exceeds the maximum of 1500 words allowed on your plan",
            InvalidRequestError,
            "text_too_long",
        ),
        (400, "Not enough credits", InsufficientCreditsError, "insufficient_credits"),
        (
            400,
            "humanization_level must be one of: standard, advanced, extreme",
            InvalidRequestError,
            "invalid_request",
        ),
        (
            400,
            "output_format must be one of: html, text, markdown",
            InvalidRequestError,
            "invalid_request",
        ),
        (
            400,
            "custom_instructions must be 1000 characters or fewer",
            InvalidRequestError,
            "invalid_request",
        ),
        (
            400,
            "The advanced and extreme humanization levels are only available for English text",
            InvalidRequestError,
            "language_not_supported",
        ),
        (
            400,
            "Your request did not pass the safety check. Please modify your input.",
            InvalidRequestError,
            "safety_check_failed",
        ),
    ],
)
def test_v1_error_mapping(
    status: int, message: str, expected_cls: type[HumanToneError], expected_code: str
) -> None:
    body = {"error": message}
    with pytest.raises(expected_cls) as excinfo:
        parse_response(status_code=status, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert excinfo.value.error_code == expected_code
    assert str(excinfo.value) == message  # verbatim preservation


def test_unknown_4xx_message_falls_back_to_status_mapping() -> None:
    body = {"error": "Some unknown 401 message we have never seen"}
    with pytest.raises(AuthenticationError) as excinfo:
        parse_response(status_code=401, body_bytes=_b(body), headers={}, endpoint="account")
    assert excinfo.value.error_code == "authentication_error"


def test_unknown_403_message_falls_back_to_permission_error() -> None:
    body = {"error": "policy says no"}
    with pytest.raises(PermissionError):
        parse_response(status_code=403, body_bytes=_b(body), headers={}, endpoint="humanize")


def test_unknown_404_message_falls_back_to_not_found() -> None:
    body = {"error": "?"}
    with pytest.raises(NotFoundError):
        parse_response(status_code=404, body_bytes=_b(body), headers={}, endpoint="account")


def test_unknown_4xx_default_is_invalid_request() -> None:
    body = {"error": "weird 422"}
    with pytest.raises(InvalidRequestError):
        parse_response(status_code=422, body_bytes=_b(body), headers={}, endpoint="humanize")


# ---------------------------------------------------------------------------
# 429 + Retry-After
# ---------------------------------------------------------------------------


def test_429_extracts_retry_after_seconds() -> None:
    body = {"error": "Too many requests"}
    with pytest.raises(RateLimitError) as excinfo:
        parse_response(
            status_code=429,
            body_bytes=_b(body),
            headers={"Retry-After": "30"},
            endpoint="humanize",
        )
    assert excinfo.value.retry_after_seconds == 30
    assert excinfo.value.status_code == 429
    assert excinfo.value.error_code == "rate_limit"


def test_429_with_any_message_still_raises() -> None:
    """Cross-endpoint 429 row uses `(any message)` — matches by status alone."""
    body = {"error": "literally anything"}
    with pytest.raises(RateLimitError):
        parse_response(
            status_code=429,
            body_bytes=_b(body),
            headers={},
            endpoint="account",
        )


# ---------------------------------------------------------------------------
# 5xx
# ---------------------------------------------------------------------------


def test_500_raises_api_error_retryable() -> None:
    body = {"error": "Internal server error"}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=500, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert excinfo.value.retryable is True
    assert str(excinfo.value) == "Internal server error"


def test_503_raises_api_error_retryable() -> None:
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=503, body_bytes=_b({}), headers={}, endpoint="account")
    assert excinfo.value.retryable is True


# ---------------------------------------------------------------------------
# v2 structured shape
# ---------------------------------------------------------------------------


def test_v2_shape_insufficient_credits_with_details() -> None:
    body = {
        "error": {
            "code": "insufficient_credits",
            "message": "Not enough credits to humanize 1,200 words.",
            "details": {"required_credits": 12, "available_credits": 4},
        },
        "request_id": "rid-v2",
    }
    with pytest.raises(InsufficientCreditsError) as excinfo:
        parse_response(status_code=400, body_bytes=_b(body), headers={}, endpoint="humanize")
    e = excinfo.value
    assert e.required_credits == 12
    assert e.available_credits == 4
    assert e.details == {"required_credits": 12, "available_credits": 4}
    assert e.request_id == "rid-v2"
    assert e.error_code == "insufficient_credits"
    assert str(e) == "Not enough credits to humanize 1,200 words."


def test_v2_shape_unknown_code_falls_back_to_status_mapping() -> None:
    body = {
        "error": {
            "code": "totally_new_code",
            "message": "future error",
            "details": {},
        }
    }
    with pytest.raises(AuthenticationError):
        parse_response(status_code=401, body_bytes=_b(body), headers={}, endpoint="account")


def test_v2_shape_known_code_authentication() -> None:
    body = {
        "error": {
            "code": "authentication_error",
            "message": "Invalid API key",
        }
    }
    with pytest.raises(AuthenticationError) as excinfo:
        parse_response(status_code=401, body_bytes=_b(body), headers={}, endpoint="account")
    assert excinfo.value.error_code == "authentication_error"


# ---------------------------------------------------------------------------
# request_id resolution (§4.14)
# ---------------------------------------------------------------------------


def test_request_id_from_body_takes_precedence() -> None:
    body = {"error": "x", "request_id": "from-body"}
    with pytest.raises(InvalidRequestError) as excinfo:
        parse_response(
            status_code=400,
            body_bytes=_b(body),
            headers={"X-Request-Id": "from-header"},
            endpoint="humanize",
        )
    assert excinfo.value.request_id == "from-body"


def test_request_id_from_header_when_body_missing() -> None:
    body = {"error": "x"}
    with pytest.raises(InvalidRequestError) as excinfo:
        parse_response(
            status_code=400,
            body_bytes=_b(body),
            headers={"X-Request-Id": "from-header"},
            endpoint="humanize",
        )
    assert excinfo.value.request_id == "from-header"


def test_request_id_none_when_neither_present() -> None:
    body = {"error": "x"}
    with pytest.raises(InvalidRequestError) as excinfo:
        parse_response(status_code=400, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert excinfo.value.request_id is None


# ---------------------------------------------------------------------------
# §4.8 step 7 — JSON parse failures
# ---------------------------------------------------------------------------


def test_malformed_json_in_5xx_yields_retryable_apierror() -> None:
    with pytest.raises(APIError) as excinfo:
        parse_response(
            status_code=500,
            body_bytes=b"<html>not json</html>",
            headers={},
            endpoint="account",
        )
    e = excinfo.value
    assert e.retryable is True
    assert e.details is not None
    assert "raw_body" in e.details
    assert "parse_error" in e.details


def test_malformed_json_in_2xx_yields_non_retryable_apierror() -> None:
    with pytest.raises(APIError) as excinfo:
        parse_response(
            status_code=200,
            body_bytes=b"not json at all",
            headers={},
            endpoint="detect",
        )
    e = excinfo.value
    assert e.retryable is False


def test_non_object_json_body_treated_as_parse_failure() -> None:
    with pytest.raises(APIError) as excinfo:
        parse_response(
            status_code=200,
            body_bytes=_b('"just a string"'),
            headers={},
            endpoint="detect",
        )
    assert "expected JSON object" in (excinfo.value.details or {}).get("parse_error", "")


def test_raw_body_is_truncated_at_4kb() -> None:
    payload = b"x" * 5000
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=500, body_bytes=payload, headers={}, endpoint="account")
    raw = (excinfo.value.details or {})["raw_body"]
    assert len(raw) == 4096


# ---------------------------------------------------------------------------
# §4.8 step 8 — coercion failures
# ---------------------------------------------------------------------------


def test_humanize_missing_content_field() -> None:
    body = {"output_format": "text", "credits_used": 1, "success": True}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert excinfo.value.retryable is False
    assert "content" in (excinfo.value.details or {}).get("coercion_error", "")


def test_humanize_unknown_output_format_value_is_coercion_failure() -> None:
    body = {
        "success": True,
        "content": "x",
        "output_format": "csv",  # unknown enum value
        "credits_used": 1,
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert "output_format" in (excinfo.value.details or {})["coercion_error"]


def test_humanize_missing_request_id_is_success_not_failure() -> None:
    body = {
        "success": True,
        "content": "x",
        "output_format": "text",
        "credits_used": 1,
    }
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert isinstance(result, HumanizeResult)
    assert result.request_id is None


def test_humanize_request_id_wrong_type_is_coercion_failure() -> None:
    body = {
        "success": True,
        "content": "x",
        "output_format": "text",
        "credits_used": 1,
        "request_id": 123,  # not a str
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="humanize")
    assert "request_id" in (excinfo.value.details or {})["coercion_error"]


def test_detect_ai_score_as_string_is_coercion_failure() -> None:
    body = {"success": True, "ai_score": "87"}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert "ai_score" in (excinfo.value.details or {})["coercion_error"]


def test_detect_ai_score_out_of_range_is_coercion_failure() -> None:
    body = {"success": True, "ai_score": 150}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert "ai_score" in (excinfo.value.details or {})["coercion_error"]


def test_detect_ai_score_as_bool_is_coercion_failure() -> None:
    """`bool` is a subclass of `int` in Python; we must explicitly reject it."""
    body = {"success": True, "ai_score": True}
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="detect")
    assert "ai_score" in (excinfo.value.details or {})["coercion_error"]


def test_account_subscription_expires_at_missing_is_success() -> None:
    body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": True,
        },
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True},  # no expires_at
    }
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert isinstance(result, AccountInfo)
    assert result.subscription.expires_at is None


def test_account_subscription_expires_at_null_is_success() -> None:
    body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": True,
        },
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True, "expires_at": None},
    }
    result = parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert isinstance(result, AccountInfo)
    assert result.subscription.expires_at is None


def test_account_subscription_expires_at_invalid_string_is_coercion_failure() -> None:
    body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": True,
        },
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True, "expires_at": "not a date"},
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert "expires_at" in (excinfo.value.details or {})["coercion_error"]


def test_account_missing_plan_object_is_coercion_failure() -> None:
    body = {
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True},
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert "plan" in (excinfo.value.details or {})["coercion_error"]


def test_account_plan_api_access_must_be_bool() -> None:
    body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": "yes",  # not bool
        },
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True, "expires_at": None},
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert "api_access" in (excinfo.value.details or {})["coercion_error"]


def test_account_credits_field_must_be_int() -> None:
    body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": True,
        },
        "credits": {"trial": "0", "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True, "expires_at": None},
    }
    with pytest.raises(APIError) as excinfo:
        parse_response(status_code=200, body_bytes=_b(body), headers={}, endpoint="account")
    assert "credits.trial" in (excinfo.value.details or {})["coercion_error"]


# ---------------------------------------------------------------------------
# Error response request_id resolution
# ---------------------------------------------------------------------------


def test_v2_request_id_lives_at_top_level_not_under_error() -> None:
    body = {
        "error": {"code": "not_found", "message": "missing"},
        "request_id": "top-level",
    }
    with pytest.raises(NotFoundError) as excinfo:
        parse_response(status_code=404, body_bytes=_b(body), headers={}, endpoint="account")
    assert excinfo.value.request_id == "top-level"
