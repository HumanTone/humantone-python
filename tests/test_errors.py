"""Tests for the exception hierarchy in `humantone.errors`."""

from __future__ import annotations

import pytest

from humantone.errors import (
    APIError,
    AuthenticationError,
    DailyLimitExceededError,
    HumanToneError,
    InsufficientCreditsError,
    InvalidRequestError,
    NetworkError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    TimeoutError,
)


def test_base_message_round_trip() -> None:
    e = HumanToneError("boom")
    assert str(e) == "boom"
    assert e.message == "boom"
    assert e.status_code is None
    assert e.request_id is None
    assert e.error_code is None
    assert e.details is None
    assert e.retryable is False


def test_repr_includes_key_fields() -> None:
    e = AuthenticationError(
        "Invalid API key",
        status_code=401,
        request_id="rid-1",
        error_code="authentication_error",
    )
    r = repr(e)
    assert "AuthenticationError" in r
    assert "Invalid API key" in r
    assert "401" in r
    assert "rid-1" in r
    assert "authentication_error" in r


def test_kw_only_enforcement_for_extra_fields() -> None:
    """`message` is positional; everything else is keyword-only."""
    with pytest.raises(TypeError):
        RateLimitError("rate", 5)  # type: ignore[misc]


def test_rate_limit_default_retry_after_is_zero() -> None:
    e = RateLimitError("rate")
    assert e.retry_after_seconds == 0


def test_rate_limit_carries_retry_after() -> None:
    e = RateLimitError("rate", retry_after_seconds=42, status_code=429)
    assert e.retry_after_seconds == 42
    assert e.status_code == 429


def test_daily_limit_status_is_200_quirk() -> None:
    e = DailyLimitExceededError(
        "Daily usage limit reached. ...",
        status_code=200,
        time_to_next_renew=3600,
    )
    assert e.status_code == 200
    assert e.time_to_next_renew == 3600


def test_daily_limit_time_to_next_renew_default_is_none() -> None:
    e = DailyLimitExceededError("Daily usage limit reached. ...", status_code=200)
    assert e.time_to_next_renew is None


def test_insufficient_credits_v2_fields_default_none() -> None:
    e = InsufficientCreditsError("Not enough credits", status_code=400)
    assert e.required_credits is None
    assert e.available_credits is None


def test_insufficient_credits_v2_fields_set() -> None:
    e = InsufficientCreditsError(
        "Not enough credits.",
        status_code=400,
        required_credits=12,
        available_credits=4,
    )
    assert e.required_credits == 12
    assert e.available_credits == 4


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (AuthenticationError, False),
        (PermissionError, False),
        (RateLimitError, False),  # default ctor doesn't set retryable; transport sets it
        (InsufficientCreditsError, False),
        (DailyLimitExceededError, False),
        (InvalidRequestError, False),
        (NotFoundError, False),
        (APIError, False),
        (TimeoutError, False),
        (NetworkError, False),
    ],
)
def test_default_ctor_retryable_is_false(cls: type[HumanToneError], expected: bool) -> None:
    """Bare ctor call defaults to retryable=False; transport supplies the
    correct value per §4.12 when constructing exceptions for raise.
    """
    e = cls("msg")
    assert e.retryable is expected


def test_retryable_can_be_set_explicitly() -> None:
    """Transport raises e.g. APIError(retryable=True) for 5xx per §4.12."""
    e = APIError("server error", retryable=True)
    assert e.retryable is True

    e2 = NetworkError("network", retryable=True)
    assert e2.retryable is True


def test_subclass_of_humantone_error() -> None:
    for cls in (
        AuthenticationError,
        PermissionError,
        RateLimitError,
        InsufficientCreditsError,
        DailyLimitExceededError,
        InvalidRequestError,
        NotFoundError,
        APIError,
        TimeoutError,
        NetworkError,
    ):
        assert issubclass(cls, HumanToneError)
        assert issubclass(cls, Exception)


def test_humantone_timeout_error_does_not_collide_with_builtin() -> None:
    """Sanity: shadowing only inside humantone namespace, builtin still works."""
    import builtins

    from humantone import TimeoutError as HTTimeoutError

    assert HTTimeoutError is not builtins.TimeoutError


def test_humantone_permission_error_does_not_collide_with_builtin() -> None:
    """Sanity: shadowing only inside humantone namespace, builtin still works."""
    import builtins

    from humantone import PermissionError as HTPermissionError

    assert HTPermissionError is not builtins.PermissionError
