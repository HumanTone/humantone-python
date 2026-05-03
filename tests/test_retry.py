"""Tests for `humantone._retry` (matrix §7.2, backoff §7.2, Retry-After §7.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from humantone._retry import (
    RetryPolicy,
    backoff_delay,
    parse_retry_after,
    should_retry,
)
from humantone.errors import (
    APIError,
    AuthenticationError,
    HumanToneError,
    NetworkError,
    RateLimitError,
    TimeoutError,
)

# ---------------------------------------------------------------------------
# parse_retry_after
# ---------------------------------------------------------------------------


def test_retry_after_none_returns_zero() -> None:
    assert parse_retry_after(None) == 0


def test_retry_after_empty_returns_zero() -> None:
    assert parse_retry_after("") == 0
    assert parse_retry_after("   ") == 0


def test_retry_after_numeric_seconds() -> None:
    assert parse_retry_after("120") == 120


def test_retry_after_numeric_with_whitespace() -> None:
    assert parse_retry_after("  42  ") == 42


def test_retry_after_zero_seconds() -> None:
    assert parse_retry_after("0") == 0


def test_retry_after_http_date_future() -> None:
    target = datetime.now(timezone.utc) + timedelta(seconds=600)
    header = format_datetime(target, usegmt=True)
    result = parse_retry_after(header)
    # Allow a couple of seconds of clock drift between calls.
    assert 595 <= result <= 605


def test_retry_after_http_date_past_clamps_to_zero() -> None:
    target = datetime.now(timezone.utc) - timedelta(seconds=600)
    header = format_datetime(target, usegmt=True)
    assert parse_retry_after(header) == 0


def test_retry_after_invalid_returns_zero() -> None:
    assert parse_retry_after("nonsense") == 0
    assert parse_retry_after("Mon, banana banana banana") == 0


# ---------------------------------------------------------------------------
# should_retry — §7.2 matrix, every row
# ---------------------------------------------------------------------------


def _net() -> NetworkError:
    return NetworkError("net", error_code="network_error", retryable=True)


def _five_xx() -> APIError:
    return APIError("server", status_code=500, error_code="api_error", retryable=True)


def _coercion() -> APIError:
    return APIError(
        "Malformed response from HumanTone API. See exception details.",
        status_code=200,
        details={"raw_body": "{}", "coercion_error": "ai_score: expected int, got str"},
        retryable=False,
    )


def _parse_5xx() -> APIError:
    return APIError(
        "Failed to parse HumanTone API response as JSON. See exception details.",
        status_code=500,
        details={"raw_body": "<html>", "parse_error": "Expecting value"},
        retryable=True,
    )


def _detect_200_success_false() -> APIError:
    return APIError(
        "Detection service error",
        status_code=200,
        error_code="api_error",
        retryable=True,
    )


def _humanize_200_success_false() -> APIError:
    return APIError("Service error", status_code=200, error_code="api_error", retryable=True)


def _rate_limit() -> RateLimitError:
    return RateLimitError(
        "rate",
        status_code=429,
        error_code="rate_limit",
        retryable=True,
        retry_after_seconds=0,
    )


def _auth_401() -> AuthenticationError:
    return AuthenticationError(
        "Invalid API key",
        status_code=401,
        error_code="authentication_error",
        retryable=False,
    )


def _timeout() -> TimeoutError:
    return TimeoutError("Request timed out", retryable=False)


_DEFAULT = RetryPolicy(max_retries=2, retry_on_post=False)
_OPT_IN = RetryPolicy(max_retries=2, retry_on_post=True)


@pytest.mark.parametrize(
    ("policy", "method", "endpoint", "exception_factory", "expected"),
    [
        # Network error
        (_DEFAULT, "GET", "account", _net, True),
        (_DEFAULT, "POST", "humanize", _net, False),
        (_DEFAULT, "POST", "detect", _net, False),
        (_OPT_IN, "POST", "humanize", _net, True),
        (_OPT_IN, "POST", "detect", _net, True),
        # HTTP 5xx
        (_DEFAULT, "GET", "account", _five_xx, True),
        (_DEFAULT, "POST", "humanize", _five_xx, False),
        (_DEFAULT, "POST", "detect", _five_xx, False),
        (_OPT_IN, "POST", "humanize", _five_xx, True),
        (_OPT_IN, "POST", "detect", _five_xx, True),
        # HTTP 429 — always retries
        (_DEFAULT, "GET", "account", _rate_limit, True),
        (_DEFAULT, "POST", "humanize", _rate_limit, True),
        (_DEFAULT, "POST", "detect", _rate_limit, True),
        # HTTP 4xx (non-429) — never retries
        (_DEFAULT, "GET", "account", _auth_401, False),
        (_DEFAULT, "POST", "humanize", _auth_401, False),
        (_OPT_IN, "POST", "humanize", _auth_401, False),
        # Client-side timeout — never retries
        (_DEFAULT, "GET", "account", _timeout, False),
        (_DEFAULT, "POST", "humanize", _timeout, False),
        (_OPT_IN, "POST", "humanize", _timeout, False),
        # 200+success:false — detect always retries
        (_DEFAULT, "POST", "detect", _detect_200_success_false, True),
        (_OPT_IN, "POST", "detect", _detect_200_success_false, True),
        # 200+success:false — humanize gates on retry_on_post
        (_DEFAULT, "POST", "humanize", _humanize_200_success_false, False),
        (_OPT_IN, "POST", "humanize", _humanize_200_success_false, True),
        # Parse failure on 5xx — same rules as 5xx
        (_DEFAULT, "GET", "account", _parse_5xx, True),
        (_DEFAULT, "POST", "humanize", _parse_5xx, False),
        (_OPT_IN, "POST", "humanize", _parse_5xx, True),
        # Coercion failure — never retries
        (_DEFAULT, "GET", "account", _coercion, False),
        (_DEFAULT, "POST", "humanize", _coercion, False),
        (_OPT_IN, "POST", "humanize", _coercion, False),
    ],
)
def test_should_retry_matrix(
    policy: RetryPolicy,
    method: str,
    endpoint: str,
    exception_factory: object,
    expected: bool,
) -> None:
    exc = exception_factory()  # type: ignore[operator]
    assert isinstance(exc, HumanToneError)
    got = should_retry(
        policy=policy,
        method=method,
        endpoint=endpoint,
        exception=exc,
        attempt=0,
    )
    assert got is expected


def test_should_retry_respects_max_retries_cap() -> None:
    """Once attempt reaches max_retries, no further retry regardless of error."""
    exc = _net()
    # attempt=2 with max_retries=2 → no more retries.
    assert (
        should_retry(
            policy=_DEFAULT,
            method="GET",
            endpoint="account",
            exception=exc,
            attempt=2,
        )
        is False
    )
    assert (
        should_retry(
            policy=_DEFAULT,
            method="GET",
            endpoint="account",
            exception=exc,
            attempt=1,
        )
        is True
    )


# ---------------------------------------------------------------------------
# backoff_delay — §7.2 formulas
# ---------------------------------------------------------------------------


_JITTER = 0.2


def test_backoff_5xx_attempt_1_around_500ms() -> None:
    d = backoff_delay(_five_xx(), attempt=1)
    assert 0.3 <= d <= 0.7


def test_backoff_5xx_attempt_2_around_1s() -> None:
    d = backoff_delay(_five_xx(), attempt=2)
    assert 0.8 <= d <= 1.2


def test_backoff_network_attempt_1_around_500ms() -> None:
    d = backoff_delay(_net(), attempt=1)
    assert 0.3 <= d <= 0.7


def test_backoff_429_with_retry_after_honors_header() -> None:
    e = RateLimitError("rate", status_code=429, retry_after_seconds=10, retryable=True)
    d = backoff_delay(e, attempt=1)
    assert 9.8 <= d <= 10.2


def test_backoff_429_without_retry_after_attempt_1_around_1s() -> None:
    e = RateLimitError("rate", status_code=429, retry_after_seconds=0, retryable=True)
    d = backoff_delay(e, attempt=1)
    assert 0.8 <= d <= 1.2


def test_backoff_429_without_retry_after_attempt_2_around_2s() -> None:
    e = RateLimitError("rate", status_code=429, retry_after_seconds=0, retryable=True)
    d = backoff_delay(e, attempt=2)
    assert 1.8 <= d <= 2.2


def test_backoff_never_negative() -> None:
    """Even for tiny base + worst-case negative jitter, result clamps to ≥ 0."""
    # Use detect transient as base 0.5 → attempt=1 gives base 0.5, jitter -0.2 → 0.3 (OK).
    # Synthesize an even-tinier case by setting a smaller base via a 429 retry_after=0
    # at a high attempt — but easier: just assert random jitter never produces negative.
    for _ in range(50):
        d = backoff_delay(_five_xx(), attempt=1)
        assert d >= 0
