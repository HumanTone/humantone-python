"""Exception hierarchy and response parser for the HumanTone SDK.

The hierarchy follows §4.9 of the development brief. The parser implements
the algorithm from §4.8 (steps 0-4 and 7-8); transport-layer steps 5-6
(network and timeout mapping) live in `_http.py` / `_async_http.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from humantone.models import (
    AccountInfo,
    Credits,
    DetectResult,
    HumanizeResult,
    OutputFormat,
    Plan,
    Subscription,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class HumanToneError(Exception):
    """Abstract base for all SDK errors.

    Every error exposes `message`, `status_code`, `request_id`, `error_code`,
    `details`, and `retryable`. See §4.10 of the brief for semantics.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        self.error_code = error_code
        self.details = details
        self.retryable = retryable

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"message={self.message!r}, "
            f"status_code={self.status_code!r}, "
            f"error_code={self.error_code!r}, "
            f"request_id={self.request_id!r})"
        )


class AuthenticationError(HumanToneError):
    """Raised on HTTP 401 (missing, invalid, or revoked API key)."""


class PermissionError(HumanToneError):
    """Raised on HTTP 403 when API access is denied (e.g. plan does not include API).

    Note: shadows Python's builtin `PermissionError` (used for filesystem
    permission failures). Use `from humantone import PermissionError as
    HumanTonePermissionError` to disambiguate if needed.
    """


class InvalidRequestError(HumanToneError):
    """Raised on HTTP 400 (or local validation failures like missing API key)."""


class NotFoundError(HumanToneError):
    """Raised on HTTP 404."""


class APIError(HumanToneError):
    """Raised on HTTP 5xx and on transient detection-service errors."""


class NetworkError(HumanToneError):
    """Raised on connection-level failures (DNS, TLS, refused) before a response."""


class TimeoutError(HumanToneError):
    """Raised when a request exceeds the client-side timeout.

    Note: shadows Python's builtin `TimeoutError` (which is an alias for
    `OSError` used in I/O contexts). Use `from humantone import
    TimeoutError as HumanToneTimeoutError` to disambiguate if needed.
    """


class RateLimitError(HumanToneError):
    """Raised on HTTP 429.

    `retry_after_seconds` is parsed from the `Retry-After` header
    (numeric seconds or HTTP-date). Defaults to 0 when the header is
    absent or unparseable.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds


class DailyLimitExceededError(HumanToneError):
    """Raised when /v1/detect returns HTTP 200 + success:false with daily-limit message.

    Note: `status_code` returns 200 for this exception, NOT 4xx or 429.
    HumanTone's daily-limit response uses HTTP 200 with `success:false` in
    the body (a quirk of the API contract). The exception still represents
    an error condition, but the underlying HTTP context is 2xx.

    `time_to_next_renew` is `None` if the API response did not include the
    field (defensive — the field is currently always present, but the SDK
    does not assume it). Callers should handle `None` as "unknown reset time".
    """

    def __init__(
        self,
        message: str,
        *,
        time_to_next_renew: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.time_to_next_renew = time_to_next_renew


class InsufficientCreditsError(HumanToneError):
    """Raised on HTTP 400 with the "Not enough credits" message.

    `required_credits` and `available_credits` are populated only when the
    API returns the v2 structured shape with `details.required_credits` /
    `details.available_credits`. Both are `None` in v1 shape responses.
    """

    def __init__(
        self,
        message: str,
        *,
        required_credits: int | None = None,
        available_credits: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.required_credits = required_credits
        self.available_credits = available_credits


# ---------------------------------------------------------------------------
# Default `retryable` per class (informational; actual retry decisions live
# in `_retry.py` per §7.2 matrix).
# ---------------------------------------------------------------------------

_RETRYABLE_DEFAULT: dict[type[HumanToneError], bool] = {
    AuthenticationError: False,
    PermissionError: False,
    RateLimitError: True,
    InsufficientCreditsError: False,
    DailyLimitExceededError: False,
    InvalidRequestError: False,
    NotFoundError: False,
    APIError: True,
    TimeoutError: False,
    NetworkError: True,
}


def _default_retryable(cls: type[HumanToneError]) -> bool:
    return _RETRYABLE_DEFAULT.get(cls, False)


# ---------------------------------------------------------------------------
# Error matching tables (§4.7, §4.11)
# ---------------------------------------------------------------------------

# Substring patterns from §4.11 (case-insensitive); first match wins.
_V1_PATTERNS: list[tuple[str, str, type[HumanToneError]]] = [
    ("daily usage limit reached", "daily_limit_exceeded", DailyLimitExceededError),
    ("not enough credits", "insufficient_credits", InsufficientCreditsError),
    ("at least 30 words", "text_too_short", InvalidRequestError),
    ("exceeds the maximum", "text_too_long", InvalidRequestError),
    ("safety check", "safety_check_failed", InvalidRequestError),
    ("only available for english", "language_not_supported", InvalidRequestError),
]

# Reverse-map for the future v2 shape (§4.11 third column).
_V2_CODE_TO_CLASS: dict[str, type[HumanToneError]] = {
    "daily_limit_exceeded": DailyLimitExceededError,
    "insufficient_credits": InsufficientCreditsError,
    "text_too_short": InvalidRequestError,
    "text_too_long": InvalidRequestError,
    "safety_check_failed": InvalidRequestError,
    "language_not_supported": InvalidRequestError,
    "authentication_error": AuthenticationError,
    "permission_denied": PermissionError,
    "not_found": NotFoundError,
    "rate_limit": RateLimitError,
    "api_error": APIError,
    "network_error": NetworkError,
    "timeout": TimeoutError,
    "invalid_request": InvalidRequestError,
}


def _http_status_fallback(status_code: int) -> tuple[type[HumanToneError], str]:
    """Map an HTTP status to (exception class, error_code) per §4.11."""
    if status_code == 401:
        return AuthenticationError, "authentication_error"
    if status_code == 403:
        return PermissionError, "permission_denied"
    if status_code == 404:
        return NotFoundError, "not_found"
    if status_code == 429:
        return RateLimitError, "rate_limit"
    if 500 <= status_code < 600:
        return APIError, "api_error"
    return InvalidRequestError, "invalid_request"


def _match_v1_error(message: str, status_code: int) -> tuple[type[HumanToneError], str]:
    """Match a v1-shape error string against §4.11, falling back to HTTP status."""
    msg_lower = message.lower()
    for pattern, code, cls in _V1_PATTERNS:
        if pattern in msg_lower:
            return cls, code
    return _http_status_fallback(status_code)


def _match_v2_error(code: str | None, status_code: int) -> tuple[type[HumanToneError], str]:
    """Resolve a v2 error.code to (class, code), falling back to HTTP status."""
    if isinstance(code, str) and code in _V2_CODE_TO_CLASS:
        return _V2_CODE_TO_CLASS[code], code
    return _http_status_fallback(status_code)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_request_id(body: object, headers: Mapping[str, str] | None) -> str | None:
    """§4.14 precedence: body.request_id > X-Request-Id header > None."""
    if isinstance(body, dict):
        rid = body.get("request_id")
        if isinstance(rid, str):
            return rid
    if headers is not None:
        v = headers.get("X-Request-Id") or headers.get("x-request-id")
        if isinstance(v, str) and v:
            return v
    return None


def _extract_message(body: object) -> str | None:
    """Pull a human-readable message from either v1 or v2 error shapes."""
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        msg = err.get("message")
        if isinstance(msg, str):
            return msg
    return None


def _truncate_raw(body_bytes: bytes) -> str:
    return body_bytes.decode("utf-8", errors="replace")[:4096]


def _coercion_apierror(body_bytes: bytes, status_code: int, field_reason: str) -> APIError:
    """Build the canonical "Malformed response" APIError from §4.8 step 8."""
    return APIError(
        "Malformed response from HumanTone API. See exception details.",
        status_code=status_code,
        details={"raw_body": _truncate_raw(body_bytes), "coercion_error": field_reason},
        retryable=False,
    )


def _parse_failure_apierror(body_bytes: bytes, status_code: int, parse_error: str) -> APIError:
    """Build the canonical "Failed to parse" APIError from §4.8 step 7."""
    retryable = 500 <= status_code < 600
    return APIError(
        "Failed to parse HumanTone API response as JSON. See exception details.",
        status_code=status_code,
        details={"raw_body": _truncate_raw(body_bytes), "parse_error": parse_error},
        retryable=retryable,
    )


# ---------------------------------------------------------------------------
# Coercion validators (§4.8 step 8)
# ---------------------------------------------------------------------------


def _is_int(v: object) -> bool:
    """True for ints that aren't bool (since bool is a subclass of int in Python)."""
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_optional_request_id(body: dict[str, Any], body_bytes: bytes) -> None:
    """Reject body.request_id when present but not a string."""
    rid = body.get("request_id")
    if rid is not None and not isinstance(rid, str):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"request_id: expected str or absent, got {type(rid).__name__}",
        )


def validate_humanize_response(
    body: dict[str, Any], body_bytes: bytes, request_id: str | None
) -> HumanizeResult:
    text = body.get("content")
    if not isinstance(text, str):
        raise _coercion_apierror(
            body_bytes, 200, f"content: expected str, got {type(text).__name__}"
        )

    of_raw = body.get("output_format")
    if not isinstance(of_raw, str):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"output_format: expected str, got {type(of_raw).__name__}",
        )
    try:
        output_format = OutputFormat(of_raw)
    except ValueError:
        raise _coercion_apierror(
            body_bytes, 200, f"output_format: unknown enum value {of_raw!r}"
        ) from None

    credits_used = body.get("credits_used")
    if not _is_int(credits_used):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"credits_used: expected int, got {type(credits_used).__name__}",
        )
    assert isinstance(credits_used, int)

    _validate_optional_request_id(body, body_bytes)

    return HumanizeResult(
        text=text,
        output_format=output_format,
        credits_used=credits_used,
        request_id=request_id,
    )


def validate_detect_response(
    body: dict[str, Any], body_bytes: bytes, request_id: str | None
) -> DetectResult:
    score = body.get("ai_score")
    if not _is_int(score):
        raise _coercion_apierror(
            body_bytes, 200, f"ai_score: expected int, got {type(score).__name__}"
        )
    assert isinstance(score, int)
    if not 0 <= score <= 100:
        raise _coercion_apierror(
            body_bytes, 200, f"ai_score: expected int in [0, 100], got {score}"
        )

    _validate_optional_request_id(body, body_bytes)

    return DetectResult(ai_score=score, request_id=request_id)


def _validate_plan(plan_raw: dict[str, Any], body_bytes: bytes) -> Plan:
    pid = plan_raw.get("id")
    name = plan_raw.get("name")
    max_words = plan_raw.get("max_words")
    monthly_credits = plan_raw.get("monthly_credits")
    api_access = plan_raw.get("api_access")

    if not isinstance(pid, str):
        raise _coercion_apierror(
            body_bytes, 200, f"plan.id: expected str, got {type(pid).__name__}"
        )
    if not isinstance(name, str):
        raise _coercion_apierror(
            body_bytes, 200, f"plan.name: expected str, got {type(name).__name__}"
        )
    if not _is_int(max_words):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"plan.max_words: expected int, got {type(max_words).__name__}",
        )
    if not _is_int(monthly_credits):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"plan.monthly_credits: expected int, got {type(monthly_credits).__name__}",
        )
    if not isinstance(api_access, bool):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"plan.api_access: expected bool, got {type(api_access).__name__}",
        )

    assert isinstance(max_words, int)
    assert isinstance(monthly_credits, int)
    return Plan(
        id=pid,
        name=name,
        max_words=max_words,
        monthly_credits=monthly_credits,
        api_access=api_access,
    )


def _validate_credits(credits_raw: dict[str, Any], body_bytes: bytes) -> Credits:
    fields: dict[str, int] = {}
    for field in ("trial", "subscription", "extra", "total"):
        v = credits_raw.get(field)
        if not _is_int(v):
            raise _coercion_apierror(
                body_bytes, 200, f"credits.{field}: expected int, got {type(v).__name__}"
            )
        assert isinstance(v, int)
        fields[field] = v
    return Credits(**fields)


def _parse_iso8601(s: str, body_bytes: bytes) -> datetime:
    """Parse ISO 8601 with `Z` suffix support on Python 3.10."""
    raw = s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise _coercion_apierror(
            body_bytes,
            200,
            f"subscription.expires_at: not a valid ISO 8601 string: {raw!r} ({e})",
        ) from None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _validate_subscription(sub_raw: dict[str, Any], body_bytes: bytes) -> Subscription:
    active = sub_raw.get("active")
    if not isinstance(active, bool):
        raise _coercion_apierror(
            body_bytes,
            200,
            f"subscription.active: expected bool, got {type(active).__name__}",
        )

    expires_raw = sub_raw.get("expires_at")
    expires_at: datetime | None
    if expires_raw is None:
        expires_at = None
    elif isinstance(expires_raw, str):
        expires_at = _parse_iso8601(expires_raw, body_bytes)
    else:
        raise _coercion_apierror(
            body_bytes,
            200,
            f"subscription.expires_at: expected str or null, got {type(expires_raw).__name__}",
        )

    return Subscription(active=active, expires_at=expires_at)


def validate_account_response(
    body: dict[str, Any], body_bytes: bytes, request_id: str | None
) -> AccountInfo:
    plan_raw = body.get("plan")
    credits_raw = body.get("credits")
    sub_raw = body.get("subscription")

    if not isinstance(plan_raw, dict):
        raise _coercion_apierror(body_bytes, 200, "plan: missing or not an object")
    if not isinstance(credits_raw, dict):
        raise _coercion_apierror(body_bytes, 200, "credits: missing or not an object")
    if not isinstance(sub_raw, dict):
        raise _coercion_apierror(body_bytes, 200, "subscription: missing or not an object")

    plan = _validate_plan(plan_raw, body_bytes)
    credits = _validate_credits(credits_raw, body_bytes)
    subscription = _validate_subscription(sub_raw, body_bytes)

    _validate_optional_request_id(body, body_bytes)

    return AccountInfo(
        plan=plan,
        credits=credits,
        subscription=subscription,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# 4xx error builder
# ---------------------------------------------------------------------------


def _build_4xx_error(
    status_code: int,
    body: dict[str, Any],
    request_id: str | None,
) -> HumanToneError:
    err = body.get("error")

    if isinstance(err, dict):
        # Future v2 structured shape.
        code = err.get("code")
        msg_raw = err.get("message")
        message = msg_raw if isinstance(msg_raw, str) else f"HTTP {status_code}"
        details_raw = err.get("details")
        details = details_raw if isinstance(details_raw, dict) else None

        exc_cls, error_code = _match_v2_error(code if isinstance(code, str) else None, status_code)

        if exc_cls is InsufficientCreditsError:
            req_credits = (
                details.get("required_credits")
                if details and _is_int(details.get("required_credits"))
                else None
            )
            avail_credits = (
                details.get("available_credits")
                if details and _is_int(details.get("available_credits"))
                else None
            )
            return InsufficientCreditsError(
                message,
                status_code=status_code,
                request_id=request_id,
                error_code=error_code,
                details=details,
                retryable=False,
                required_credits=req_credits,
                available_credits=avail_credits,
            )
        return exc_cls(
            message,
            status_code=status_code,
            request_id=request_id,
            error_code=error_code,
            details=details,
            retryable=_default_retryable(exc_cls),
        )

    # v1 shape: error is a string (or absent / non-string).
    message = err if isinstance(err, str) else f"HTTP {status_code}"
    match_string = err if isinstance(err, str) else ""
    exc_cls, error_code = _match_v1_error(match_string, status_code)

    return exc_cls(
        message,
        status_code=status_code,
        request_id=request_id,
        error_code=error_code,
        retryable=_default_retryable(exc_cls),
    )


# ---------------------------------------------------------------------------
# Top-level response parser (§4.8)
# ---------------------------------------------------------------------------


def parse_response(
    *,
    status_code: int,
    body_bytes: bytes,
    headers: Mapping[str, str] | None,
    endpoint: str,
) -> HumanizeResult | DetectResult | AccountInfo:
    """Implements §4.8 algorithm steps 0-4 and 7-8.

    Steps 5-6 (network and timeout exception mapping) are handled by the
    transport layer, which catches library-specific exceptions and raises
    `NetworkError` / `TimeoutError` directly.

    `endpoint` is one of "humanize", "detect", "account" — used to dispatch
    the success-path validator.
    """
    # Step 0: parse JSON.
    try:
        body = json.loads(body_bytes.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _parse_failure_apierror(body_bytes, status_code, str(e)) from None

    if not isinstance(body, dict):
        # Body parsed but is not a JSON object. Treat as parse failure.
        raise _parse_failure_apierror(body_bytes, status_code, "expected JSON object at top level")

    request_id = _resolve_request_id(body, headers)

    # Step 1: 2xx
    if 200 <= status_code < 300:
        if body.get("success") is False:
            error_msg = body.get("error")
            time_to_next_renew = body.get("time_to_next_renew")
            ttnr = time_to_next_renew if _is_int(time_to_next_renew) else None

            if isinstance(error_msg, str) and error_msg.lower().startswith(
                "daily usage limit reached"
            ):
                raise DailyLimitExceededError(
                    error_msg,
                    status_code=200,
                    request_id=request_id,
                    error_code="daily_limit_exceeded",
                    retryable=False,
                    time_to_next_renew=ttnr,
                )

            # Detection-service transient error (or reserved humanize variant).
            # Whether to actually retry is decided by §7.2 retry matrix.
            default_msg = "Detection service error" if endpoint == "detect" else "Service error"
            message = error_msg if isinstance(error_msg, str) else default_msg
            raise APIError(
                message,
                status_code=status_code,
                request_id=request_id,
                error_code="api_error",
                retryable=True,
            )

        # Success path — dispatch to validator.
        if endpoint == "humanize":
            return validate_humanize_response(body, body_bytes, request_id)
        if endpoint == "detect":
            return validate_detect_response(body, body_bytes, request_id)
        if endpoint == "account":
            return validate_account_response(body, body_bytes, request_id)
        raise ValueError(f"Unknown endpoint: {endpoint!r}")  # pragma: no cover

    # Step 3: 429
    if status_code == 429:
        # Caller passes Retry-After via headers; transport extracts and constructs
        # RateLimitError so the parser doesn't need to know about retry policy.
        from humantone._retry import parse_retry_after  # local to avoid cycle

        retry_after = parse_retry_after(headers.get("Retry-After") if headers else None)
        message = _extract_message(body) or "Rate limited"
        raise RateLimitError(
            message,
            status_code=429,
            request_id=request_id,
            error_code="rate_limit",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    # Step 2: 4xx (non-429)
    if 400 <= status_code < 500:
        raise _build_4xx_error(status_code, body, request_id)

    # Step 4: 5xx
    if 500 <= status_code < 600:
        message = _extract_message(body) or "Internal server error"
        raise APIError(
            message,
            status_code=status_code,
            request_id=request_id,
            error_code="api_error",
            retryable=True,
        )

    # Defensive: unexpected status (1xx, 3xx). Not retried.
    message = _extract_message(body) or f"Unexpected HTTP status {status_code}"
    raise APIError(
        message,
        status_code=status_code,
        request_id=request_id,
        error_code="api_error",
        retryable=False,
    )


__all__ = [
    "APIError",
    "AuthenticationError",
    "DailyLimitExceededError",
    "HumanToneError",
    "InsufficientCreditsError",
    "InvalidRequestError",
    "NetworkError",
    "NotFoundError",
    "PermissionError",
    "RateLimitError",
    "TimeoutError",
    "parse_response",
    "validate_account_response",
    "validate_detect_response",
    "validate_humanize_response",
]
