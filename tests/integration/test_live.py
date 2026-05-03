"""Integration tests against the real HumanTone API.

These tests are gated behind the `HUMANTONE_TEST_API_KEY` env var and the
`integration` pytest marker. They are deselected by default — run them
explicitly before each release with:

    HUMANTONE_TEST_API_KEY=ht_... pytest -m integration

DO NOT run in CI for external contributors — they cost real credits and
require access to a paid HumanTone account.
"""

from __future__ import annotations

import os

import pytest

from humantone import (
    AccountInfo,
    AuthenticationError,
    DetectResult,
    HumanizationLevel,
    HumanizeResult,
    HumanTone,
)

pytestmark = pytest.mark.integration


_API_KEY = os.getenv("HUMANTONE_TEST_API_KEY", "")
_BASE_URL = os.getenv("HUMANTONE_TEST_BASE_URL")  # optional override

requires_test_key = pytest.mark.skipif(
    not _API_KEY,
    reason="HUMANTONE_TEST_API_KEY not set; skipping integration tests",
)


SAMPLE_TEXT = (
    "Artificial intelligence has transformed how content teams work. "
    "Writers now use AI tools to draft, edit, and polish their content "
    "at scale, with reviewers focused on tone and accuracy. "
    "This has led to faster turnaround and broader experimentation across teams."
)


@requires_test_key
def test_humanize_standard() -> None:
    client = HumanTone(api_key=_API_KEY, base_url=_BASE_URL)
    try:
        result = client.humanize(text=SAMPLE_TEXT, level=HumanizationLevel.STANDARD)
    finally:
        client.close()
    assert isinstance(result, HumanizeResult)
    assert result.text
    assert result.credits_used >= 1


@requires_test_key
def test_humanize_advanced() -> None:
    client = HumanTone(api_key=_API_KEY, base_url=_BASE_URL)
    try:
        result = client.humanize(text=SAMPLE_TEXT, level=HumanizationLevel.ADVANCED)
    finally:
        client.close()
    assert isinstance(result, HumanizeResult)


@requires_test_key
def test_humanize_extreme() -> None:
    client = HumanTone(api_key=_API_KEY, base_url=_BASE_URL)
    try:
        result = client.humanize(text=SAMPLE_TEXT, level=HumanizationLevel.EXTREME)
    finally:
        client.close()
    assert isinstance(result, HumanizeResult)


@requires_test_key
def test_detect() -> None:
    client = HumanTone(api_key=_API_KEY, base_url=_BASE_URL)
    try:
        result = client.detect(text=SAMPLE_TEXT)
    finally:
        client.close()
    assert isinstance(result, DetectResult)
    assert 0 <= result.ai_score <= 100


@requires_test_key
def test_account() -> None:
    client = HumanTone(api_key=_API_KEY, base_url=_BASE_URL)
    try:
        info = client.account.get()
    finally:
        client.close()
    assert isinstance(info, AccountInfo)
    assert info.plan.api_access is True


@requires_test_key
def test_unauthorized_key_raises_authentication_error() -> None:
    """Use a structurally-valid but server-unknown key (per §9.4 guidance)."""
    fake_key = "ht_" + "0" * 64
    client = HumanTone(api_key=fake_key, base_url=_BASE_URL)
    try:
        with pytest.raises(AuthenticationError):
            client.account.get()
    finally:
        client.close()
