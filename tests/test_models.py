"""Tests for `humantone.models`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from humantone.models import (
    AccountInfo,
    Credits,
    DetectResult,
    HumanizationLevel,
    HumanizeResult,
    OutputFormat,
    Plan,
    Subscription,
)


def test_humanization_level_values() -> None:
    assert HumanizationLevel.STANDARD.value == "standard"
    assert HumanizationLevel.ADVANCED.value == "advanced"
    assert HumanizationLevel.EXTREME.value == "extreme"


def test_output_format_values() -> None:
    assert OutputFormat.TEXT.value == "text"
    assert OutputFormat.HTML.value == "html"
    assert OutputFormat.MARKDOWN.value == "markdown"


def test_humanize_result_construction() -> None:
    r = HumanizeResult(
        text="hello",
        output_format=OutputFormat.TEXT,
        credits_used=3,
        request_id="req-123",
    )
    assert r.text == "hello"
    assert r.output_format is OutputFormat.TEXT
    assert r.credits_used == 3
    assert r.request_id == "req-123"


def test_humanize_result_is_frozen() -> None:
    r = HumanizeResult(text="x", output_format=OutputFormat.HTML, credits_used=1, request_id=None)
    with pytest.raises(FrozenInstanceError):
        r.text = "y"  # type: ignore[misc]


def test_detect_result_default_request_id() -> None:
    r = DetectResult(ai_score=42)
    assert r.ai_score == 42
    assert r.request_id is None


def test_account_info_construction() -> None:
    info = AccountInfo(
        plan=Plan(id="p", name="Pro", max_words=1500, monthly_credits=1000, api_access=True),
        credits=Credits(trial=0, subscription=820, extra=150, total=970),
        subscription=Subscription(
            active=True, expires_at=datetime(2026, 5, 8, tzinfo=timezone.utc)
        ),
    )
    assert info.plan.max_words == 1500
    assert info.credits.total == 970
    assert info.subscription.active is True
    assert info.subscription.expires_at is not None
    assert info.subscription.expires_at.tzinfo is timezone.utc
    assert info.request_id is None


def test_subscription_expires_at_can_be_none() -> None:
    s = Subscription(active=True, expires_at=None)
    assert s.expires_at is None
