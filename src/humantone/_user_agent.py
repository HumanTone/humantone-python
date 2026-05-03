"""User-Agent string construction (§7.5) and SDK version resolution (§7.4)."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

from humantone._version import __version__ as _FALLBACK_VERSION  # noqa: N812


def resolve_sdk_version() -> str:
    """Resolve the installed `humantone-sdk` distribution version.

    Falls back to the hardcoded `_version.__version__` when the package
    metadata is unavailable (e.g., running from a source checkout without
    `pip install -e .`, or from a frozen executable).
    """
    try:
        return version("humantone-sdk")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def _python_version() -> str:
    """Sanitized "M.m.p" — no `b1`/`rc1`/`+local` noise from `sys.version`."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def build_user_agent(suffix: str | None = None) -> str:
    """Build the User-Agent header value per §7.5.

    Empty / whitespace-only `suffix` is treated as absent (no trailing space).
    A non-empty suffix is appended after a single space, after `.strip()`.
    """
    base = f"humantone-python/{resolve_sdk_version()} (python/{_python_version()})"
    suffix_clean = (suffix or "").strip()
    if suffix_clean:
        return f"{base} {suffix_clean}"
    return base


__all__ = ["build_user_agent", "resolve_sdk_version"]
