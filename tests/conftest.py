"""Shared pytest fixtures for the HumanTone SDK test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

VALID_API_KEY = "ht_" + "a" * 64
FAKE_BASE_URL = "https://api.test.local"
_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def api_key() -> str:
    return VALID_API_KEY


@pytest.fixture
def base_url() -> str:
    return FAKE_BASE_URL


@pytest.fixture
def load_fixture() -> Any:
    def _load(name: str) -> dict[str, Any]:
        path = _FIXTURES_DIR / name
        with path.open(encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]

    return _load


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip HUMANTONE_* env vars from every test by default.

    Tests that need a specific env value set it explicitly via monkeypatch.
    """
    for var in ("HUMANTONE_API_KEY", "HUMANTONE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace sync transport sleep with a no-op so retry tests are fast.

    Async transport sleep is patched per-test because pytest-asyncio fixtures
    interact differently with monkeypatch.
    """
    import humantone._http

    monkeypatch.setattr(humantone._http, "_sleep", lambda _seconds: None)


@pytest.fixture
def integration_key() -> str | None:
    return os.getenv("HUMANTONE_TEST_API_KEY")
