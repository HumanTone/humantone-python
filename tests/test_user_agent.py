"""Tests for `humantone._user_agent` (§7.5)."""

from __future__ import annotations

import re
import sys

import pytest

from humantone import _user_agent
from humantone._user_agent import build_user_agent, resolve_sdk_version

_UA_REGEX = re.compile(
    r"^humantone-python/\d+\.\d+\.\d+(?:[-+.][a-zA-Z0-9.]+)? \(python/\d+\.\d+\.\d+\)"
    r"(?: .+)?$"
)


def test_default_user_agent_matches_regex() -> None:
    ua = build_user_agent()
    assert _UA_REGEX.match(ua)


def test_default_user_agent_uses_sanitized_python_version() -> None:
    ua = build_user_agent()
    expected_py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert f"(python/{expected_py})" in ua
    # No b1/rc1/+local noise on python segment.
    assert "b" not in ua.split("python/")[1].split(")")[0]
    assert "rc" not in ua.split("python/")[1].split(")")[0]


@pytest.mark.parametrize(
    ("supplied", "expected_suffix"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("my-app/1.0", " my-app/1.0"),
        ("  my-app/1.0  ", " my-app/1.0"),
    ],
)
def test_suffix_normalization(supplied: str | None, expected_suffix: str) -> None:
    ua = build_user_agent(supplied)
    if expected_suffix:
        assert ua.endswith(expected_suffix)
        # Single space between base and suffix.
        assert ")  " not in ua
    else:
        assert ua.endswith(")")


def test_resolve_sdk_version_returns_string() -> None:
    v = resolve_sdk_version()
    assert isinstance(v, str)
    assert v  # non-empty


def test_resolve_sdk_version_falls_back_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import PackageNotFoundError

    def _raise(_name: str) -> str:
        raise PackageNotFoundError("simulated")

    monkeypatch.setattr(_user_agent, "version", _raise)
    assert resolve_sdk_version() == _user_agent._FALLBACK_VERSION
