"""Retry policy (§7.2 matrix) and backoff calculation (§7.2 + §7.3).

Pure functions only — sleeping is the transport's responsibility so this
module stays trivial to test in isolation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from humantone.errors import APIError, HumanToneError, RateLimitError

_JITTER_RANGE = 0.2  # ± seconds on every backoff


def parse_retry_after(header: str | None) -> int:
    """Parse a `Retry-After` header value to seconds (RFC 7231).

    Accepts both numeric (`120`) and HTTP-date (`Wed, 21 Oct 2026 07:28:00 GMT`)
    forms. Returns 0 when the header is absent or malformed — callers should
    treat 0 as "no useful header" and fall back to exponential backoff.
    """
    if header is None:
        return 0
    header = header.strip()
    if not header:
        return 0
    if header.isdigit():
        return int(header)
    try:
        ts = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return 0
    if ts is None:
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    diff = int((ts - datetime.now(timezone.utc)).total_seconds())
    return max(0, diff)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry configuration. `max_retries=2` → up to 3 total attempts."""

    max_retries: int = 2
    retry_on_post: bool = False


def should_retry(
    *,
    policy: RetryPolicy,
    method: str,
    endpoint: str,
    exception: HumanToneError,
    attempt: int,
) -> bool:
    """Decide whether to retry given §7.2 matrix.

    `attempt` is the count of retries already performed (0 = first try just
    failed, 1 = first retry just failed, ...). Returns True iff another
    retry should happen now.
    """
    if attempt >= policy.max_retries:
        return False

    # Per §4.12: only retryable=True classes are candidates. This excludes
    # AuthenticationError, PermissionError, NotFoundError, InvalidRequestError,
    # InsufficientCreditsError, DailyLimitExceededError, TimeoutError, and
    # APIError variants explicitly marked non-retryable (parse failure on
    # 2xx/4xx, coercion failure).
    if not exception.retryable:
        return False

    # 429 always retries on every method (rate-limit responses arrive before
    # any work is done server-side, so retry is safe even on POST).
    if isinstance(exception, RateLimitError):
        return True

    # GET endpoints retry any retryable error.
    if method.upper() == "GET":
        return True

    # POST exception: detect's 200+success:false transient backend error
    # always retries, regardless of retry_on_post (the response carries
    # status_code=200 and is APIError(retryable=True), but it's not a
    # billing-relevant operation since detect doesn't consume credits).
    if isinstance(exception, APIError) and exception.status_code == 200 and endpoint == "detect":
        return True

    # POST: network errors, 5xx, parse-failure-on-5xx, and humanize's
    # 200+success:false reserved variant all gate on retry_on_post.
    return policy.retry_on_post


def backoff_delay(exception: HumanToneError, attempt: int) -> float:
    """Seconds to wait before the next retry. `attempt` starts at 1.

    - 5xx, network, transient detection error: 0.5s * 2^(attempt-1) +/- 0.2s
    - 429 with parseable Retry-After: header_seconds +/- 0.2s
    - 429 without Retry-After: 1s * 2^(attempt-1) +/- 0.2s

    Result is clamped to ≥ 0.
    """
    if isinstance(exception, RateLimitError) and exception.retry_after_seconds > 0:
        base = float(exception.retry_after_seconds)
    elif isinstance(exception, RateLimitError):
        base = 1.0 * (2 ** (attempt - 1))
    else:
        base = 0.5 * (2 ** (attempt - 1))

    jitter = random.uniform(-_JITTER_RANGE, _JITTER_RANGE)
    return max(0.0, base + jitter)


__all__ = [
    "RetryPolicy",
    "backoff_delay",
    "parse_retry_after",
    "should_retry",
]
