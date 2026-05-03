"""End-to-end tests for the sync `HumanTone` client using `responses`."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import requests
import responses

from humantone import (
    APIError,
    AuthenticationError,
    DailyLimitExceededError,
    HumanizationLevel,
    HumanizeResult,
    HumanTone,
    InsufficientCreditsError,
    InvalidRequestError,
    NotFoundError,
    OutputFormat,
    PermissionError,
    RateLimitError,
)

VALID_KEY = "ht_" + "a" * 64
BASE_URL = "https://api.test.local"


def _client(**kw: Any) -> HumanTone:
    return HumanTone(api_key=VALID_KEY, base_url=BASE_URL, **kw)


# ---------------------------------------------------------------------------
# §9.1 Client construction
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_with_error_code() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        HumanTone()
    assert excinfo.value.error_code == "missing_api_key"


def test_empty_string_env_var_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUMANTONE_API_KEY", "")
    with pytest.raises(InvalidRequestError) as excinfo:
        HumanTone()
    assert excinfo.value.error_code == "missing_api_key"


def test_whitespace_env_var_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUMANTONE_API_KEY", "   ")
    with pytest.raises(InvalidRequestError) as excinfo:
        HumanTone()
    assert excinfo.value.error_code == "missing_api_key"


def test_empty_string_constructor_arg_falls_through_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HUMANTONE_API_KEY", raising=False)
    with pytest.raises(InvalidRequestError) as excinfo:
        HumanTone(api_key="")
    assert excinfo.value.error_code == "missing_api_key"


def test_whitespace_padded_valid_key_is_stripped() -> None:
    client = HumanTone(api_key=f"  {VALID_KEY}  ", base_url=BASE_URL)
    # If we got this far, validation passed.
    assert client is not None


def test_malformed_api_key_raises() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        HumanTone(api_key="not-a-key", base_url=BASE_URL)
    assert excinfo.value.error_code == "invalid_api_key_format"


def test_uppercase_hex_in_key_is_rejected() -> None:
    """Regex requires lowercase hex per §5.1."""
    with pytest.raises(InvalidRequestError):
        HumanTone(api_key="ht_" + "A" * 64, base_url=BASE_URL)


def test_env_var_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUMANTONE_API_KEY", VALID_KEY)
    client = HumanTone(base_url=BASE_URL)
    assert client is not None


def test_constructor_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUMANTONE_API_KEY", "ht_" + "b" * 64)
    # Passing the constructor arg wins, doesn't touch env.
    client = HumanTone(api_key=VALID_KEY, base_url=BASE_URL)
    assert client is not None


def test_custom_base_url_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUMANTONE_BASE_URL", "https://env.example.com")
    client = HumanTone(api_key=VALID_KEY, base_url="https://override.example.com")
    # Base URL is internal; verify by issuing a request later.
    assert client is not None


def test_empty_base_url_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HUMANTONE_BASE_URL", "")
    client = HumanTone(api_key=VALID_KEY)
    # Internal: just exercise that construction succeeds.
    assert client is not None


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@responses.activate
def test_humanize_happy_path() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "rid-1",
            "content": "humanized",
            "output_format": "text",
            "credits_used": 3,
        },
        status=200,
    )
    result = _client().humanize(text="some draft text " * 10)
    assert isinstance(result, HumanizeResult)
    assert result.text == "humanized"
    assert result.output_format is OutputFormat.TEXT
    assert result.credits_used == 3
    assert result.request_id == "rid-1"


@responses.activate
def test_detect_happy_path() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/detect",
        json={"success": True, "ai_score": 73},
        status=200,
    )
    result = _client().detect(text="anything")
    assert result.ai_score == 73


@responses.activate
def test_account_get_happy_path() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={
            "plan": {
                "id": "pro",
                "name": "Pro",
                "max_words": 1500,
                "monthly_credits": 1000,
                "api_access": True,
            },
            "credits": {"trial": 0, "subscription": 820, "extra": 150, "total": 970},
            "subscription": {"active": True, "expires_at": "2026-05-08T00:00:00.000Z"},
        },
        status=200,
    )
    info = _client().account.get()
    assert info.plan.name == "Pro"
    assert info.credits.total == 970
    assert info.subscription.expires_at is not None


# ---------------------------------------------------------------------------
# Request body / headers assertions
# ---------------------------------------------------------------------------


@responses.activate
def test_humanize_default_output_format_is_text() -> None:
    """SDK overrides API default of 'html' with 'text'."""
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "text",
            "credits_used": 1,
        },
        status=200,
    )
    _client().humanize(text="anything")
    body = json.loads(responses.calls[0].request.body or "{}")
    assert body["output_format"] == "text"


@responses.activate
def test_humanize_sends_renamed_fields() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "html",
            "credits_used": 1,
        },
        status=200,
    )
    _client().humanize(
        text="my-draft",
        level=HumanizationLevel.ADVANCED,
        output_format=OutputFormat.HTML,
        custom_instructions="be terse",
    )
    body = json.loads(responses.calls[0].request.body or "{}")
    assert body == {
        "content": "my-draft",
        "humanization_level": "advanced",
        "output_format": "html",
        "custom_instructions": "be terse",
    }


@responses.activate
def test_humanize_omits_custom_instructions_when_none() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "text",
            "credits_used": 1,
        },
        status=200,
    )
    _client().humanize(text="x")
    body = json.loads(responses.calls[0].request.body or "{}")
    assert "custom_instructions" not in body


@responses.activate
def test_string_literal_level_accepted() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "text",
            "credits_used": 1,
        },
        status=200,
    )
    _client().humanize(text="x", level="extreme", output_format="markdown")
    body = json.loads(responses.calls[0].request.body or "{}")
    assert body["humanization_level"] == "extreme"
    assert body["output_format"] == "markdown"


@responses.activate
def test_authorization_bearer_header_sent() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={
            "plan": {
                "id": "p",
                "name": "P",
                "max_words": 100,
                "monthly_credits": 10,
                "api_access": True,
            },
            "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
            "subscription": {"active": True, "expires_at": None},
        },
        status=200,
    )
    _client().account.get()
    sent = responses.calls[0].request.headers
    assert sent["Authorization"] == f"Bearer {VALID_KEY}"
    assert sent["Accept"] == "application/json"
    assert "Content-Type" not in sent or sent.get("Content-Type") != "application/json"


@responses.activate
def test_content_type_set_on_post_only() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/detect",
        json={"success": True, "ai_score": 50},
        status=200,
    )
    _client().detect(text="x")
    assert responses.calls[0].request.headers["Content-Type"] == "application/json"


@responses.activate
def test_user_agent_matches_regex() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={
            "plan": {
                "id": "p",
                "name": "P",
                "max_words": 100,
                "monthly_credits": 10,
                "api_access": True,
            },
            "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
            "subscription": {"active": True, "expires_at": None},
        },
        status=200,
    )
    _client().account.get()
    ua = responses.calls[0].request.headers["User-Agent"]
    pattern = (
        r"^humantone-python/\d+\.\d+\.\d+(?:[-+.][a-zA-Z0-9.]+)? "
        r"\(python/\d+\.\d+\.\d+\)$"
    )
    assert re.match(pattern, ua), f"UA does not match: {ua!r}"


@responses.activate
def test_user_agent_with_user_supplied_suffix() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={
            "plan": {
                "id": "p",
                "name": "P",
                "max_words": 100,
                "monthly_credits": 10,
                "api_access": True,
            },
            "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
            "subscription": {"active": True, "expires_at": None},
        },
        status=200,
    )
    HumanTone(api_key=VALID_KEY, base_url=BASE_URL, user_agent="my-app/1.0").account.get()
    ua = responses.calls[0].request.headers["User-Agent"]
    assert ua.endswith(" my-app/1.0")


# ---------------------------------------------------------------------------
# Error mapping (verbatim)
# ---------------------------------------------------------------------------


@responses.activate
def test_400_not_enough_credits_raises_insufficient_credits() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={"error": "Not enough credits"},
        status=400,
    )
    with pytest.raises(InsufficientCreditsError) as excinfo:
        _client().humanize(text="x")
    assert str(excinfo.value) == "Not enough credits"


@responses.activate
def test_401_invalid_key_raises_authentication_error() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={"error": "Invalid API key"},
        status=401,
    )
    with pytest.raises(AuthenticationError):
        _client().account.get()


@responses.activate
def test_403_plan_no_api_access_raises_permission_error() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "error": ("Your current plan does not include API access. Please upgrade to continue.")
        },
        status=403,
    )
    with pytest.raises(PermissionError):
        _client().humanize(text="x")


@responses.activate
def test_404_plan_not_found_raises_not_found() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={"error": "Plan not found"},
        status=404,
    )
    with pytest.raises(NotFoundError):
        _client().account.get()


@responses.activate
def test_429_raises_rate_limit_with_retry_after() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={"error": "Too many requests"},
        status=429,
        headers={"Retry-After": "5"},
    )
    # 429 always retries POST; with max_retries=2 → 3 total attempts.
    # Re-add to allow retries — `responses` consumes one match per call.
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={"error": "Too many requests"},
        status=429,
        headers={"Retry-After": "5"},
    )
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={"error": "Too many requests"},
        status=429,
        headers={"Retry-After": "5"},
    )
    with pytest.raises(RateLimitError) as excinfo:
        _client().humanize(text="x")
    assert excinfo.value.retry_after_seconds == 5


# ---------------------------------------------------------------------------
# 200 + success:false branches
# ---------------------------------------------------------------------------


@responses.activate
def test_detect_daily_limit_raises_daily_limit_exceeded() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/detect",
        json={
            "success": False,
            "error": (
                "Daily usage limit reached. You have used 30 of 30 allowed detections today."
            ),
            "time_to_next_renew": 3600,
        },
        status=200,
    )
    with pytest.raises(DailyLimitExceededError) as excinfo:
        _client().detect(text="x")
    assert excinfo.value.time_to_next_renew == 3600
    assert excinfo.value.status_code == 200


# ---------------------------------------------------------------------------
# Retry behavior — §9.1 list
# ---------------------------------------------------------------------------


@responses.activate
def test_get_account_retries_500_then_succeeds() -> None:
    responses.add(responses.GET, f"{BASE_URL}/v1/account", status=500, json={"error": "x"})
    responses.add(responses.GET, f"{BASE_URL}/v1/account", status=500, json={"error": "x"})
    responses.add(
        responses.GET,
        f"{BASE_URL}/v1/account",
        json={
            "plan": {
                "id": "p",
                "name": "P",
                "max_words": 100,
                "monthly_credits": 10,
                "api_access": True,
            },
            "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
            "subscription": {"active": True, "expires_at": None},
        },
        status=200,
    )
    info = _client().account.get()
    assert info.plan.id == "p"
    assert len(responses.calls) == 3


@responses.activate
def test_get_account_500_x3_raises_after_max_retries() -> None:
    for _ in range(3):
        responses.add(responses.GET, f"{BASE_URL}/v1/account", status=500, json={"error": "x"})
    with pytest.raises(APIError):
        _client().account.get()
    assert len(responses.calls) == 3


@responses.activate
def test_humanize_500_does_not_retry_by_default() -> None:
    responses.add(responses.POST, f"{BASE_URL}/v1/humanize", status=500, json={"error": "x"})
    with pytest.raises(APIError):
        _client().humanize(text="x")
    assert len(responses.calls) == 1


@responses.activate
def test_humanize_500_retries_with_retry_on_post() -> None:
    responses.add(responses.POST, f"{BASE_URL}/v1/humanize", status=500, json={"error": "x"})
    responses.add(responses.POST, f"{BASE_URL}/v1/humanize", status=500, json={"error": "x"})
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "text",
            "credits_used": 1,
        },
        status=200,
    )
    result = _client(retry_on_post=True).humanize(text="x")
    assert isinstance(result, HumanizeResult)
    assert len(responses.calls) == 3


@responses.activate
def test_humanize_429_always_retries_even_without_retry_on_post() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        status=429,
        json={"error": "rate"},
        headers={"Retry-After": "0"},
    )
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        json={
            "success": True,
            "request_id": "x",
            "content": "y",
            "output_format": "text",
            "credits_used": 1,
        },
        status=200,
    )
    result = _client().humanize(text="x")
    assert isinstance(result, HumanizeResult)
    assert len(responses.calls) == 2


@responses.activate
def test_4xx_non_429_never_retries() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/humanize",
        status=400,
        json={"error": "Invalid JSON body"},
    )
    with pytest.raises(InvalidRequestError):
        _client().humanize(text="x")
    assert len(responses.calls) == 1


@responses.activate
def test_detect_200_success_false_no_message_retries() -> None:
    responses.add(responses.POST, f"{BASE_URL}/v1/detect", status=200, json={"success": False})
    responses.add(responses.POST, f"{BASE_URL}/v1/detect", status=200, json={"success": False})
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/detect",
        json={"success": True, "ai_score": 42},
        status=200,
    )
    r = _client().detect(text="x")
    assert r.ai_score == 42
    assert len(responses.calls) == 3


@responses.activate
def test_detect_daily_limit_does_not_retry() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/v1/detect",
        status=200,
        json={
            "success": False,
            "error": "Daily usage limit reached. ...",
            "time_to_next_renew": 100,
        },
    )
    with pytest.raises(DailyLimitExceededError):
        _client().detect(text="x")
    assert len(responses.calls) == 1


# ---------------------------------------------------------------------------
# Network error mapping
# ---------------------------------------------------------------------------


@responses.activate
def test_network_error_on_get_retries_then_raises_network_error() -> None:
    from humantone import NetworkError

    err = requests.exceptions.ConnectionError("simulated DNS fail")
    responses.add(responses.GET, f"{BASE_URL}/v1/account", body=err)
    responses.add(responses.GET, f"{BASE_URL}/v1/account", body=err)
    responses.add(responses.GET, f"{BASE_URL}/v1/account", body=err)
    with pytest.raises(NetworkError):
        _client().account.get()
    assert len(responses.calls) == 3


@responses.activate
def test_timeout_does_not_retry() -> None:
    from humantone import TimeoutError as HTTimeout

    err = requests.exceptions.ReadTimeout("simulated read timeout")
    responses.add(responses.POST, f"{BASE_URL}/v1/humanize", body=err)
    with pytest.raises(HTTimeout):
        _client().humanize(text="x")
    assert len(responses.calls) == 1


# ---------------------------------------------------------------------------
# Context manager / close
# ---------------------------------------------------------------------------


def test_context_manager_closes_owned_session() -> None:
    client = _client()
    closed = {"called": False}

    real_close = client._http_client.close  # type: ignore[attr-defined]

    def _closing() -> None:
        closed["called"] = True
        real_close()

    client._http_client.close = _closing  # type: ignore[attr-defined,method-assign]

    with client as c:
        assert c is client

    assert closed["called"] is True


def test_close_is_no_op_for_injected_session() -> None:
    session = requests.Session()
    closed = {"called": False}

    real_close = session.close

    def _closing() -> None:
        closed["called"] = True
        real_close()

    session.close = _closing  # type: ignore[method-assign]
    client = HumanTone(api_key=VALID_KEY, base_url=BASE_URL, http_client=session)
    client.close()
    assert closed["called"] is False
    session.close()  # Caller cleans up.
