"""Tests for the PEP 562 lazy import behavior in `humantone/__init__.py`.

The contract: `from humantone import HumanTone` must succeed even when
`httpx` is not installed. `from humantone import AsyncHumanTone` (or
`humantone.AsyncHumanTone`) must raise a helpful `ImportError` with an
install hint when `httpx` is missing.
"""

from __future__ import annotations

import sys
from importlib import import_module

import pytest


def _purge_humantone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every cached `humantone[.*]` module so a re-import is clean."""
    for name in [m for m in list(sys.modules) if m == "humantone" or m.startswith("humantone.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_sync_import_works_without_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing HumanTone alone must NOT trigger an `httpx` import."""
    _purge_humantone(monkeypatch)
    monkeypatch.setitem(sys.modules, "httpx", None)  # blocks `import httpx`
    pkg = import_module("humantone")
    HumanTone = pkg.HumanTone  # noqa: N806
    assert HumanTone is not None


def test_async_import_raises_helpful_error_without_httpx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accessing AsyncHumanTone without httpx raises ImportError with install hint."""
    _purge_humantone(monkeypatch)
    monkeypatch.setitem(sys.modules, "httpx", None)
    pkg = import_module("humantone")
    with pytest.raises(ImportError, match=r"pip install 'humantone-sdk\[async\]'"):
        _ = pkg.AsyncHumanTone


def test_async_import_succeeds_when_httpx_available() -> None:
    """In the dev environment httpx is installed, so the lazy import should resolve."""
    import humantone

    AsyncHumanTone = humantone.AsyncHumanTone  # noqa: N806
    assert AsyncHumanTone is not None
    assert AsyncHumanTone.__name__ == "AsyncHumanTone"


def test_dir_lists_async_humantone() -> None:
    """`AsyncHumanTone` is in `__all__` so it shows up via `dir()`."""
    import humantone

    assert "AsyncHumanTone" in dir(humantone)
    assert "AsyncHumanTone" in humantone.__all__


def test_unknown_attribute_raises_attribute_error() -> None:
    import humantone

    with pytest.raises(AttributeError, match="no attribute 'doesnt_exist'"):
        _ = humantone.doesnt_exist  # type: ignore[attr-defined]
