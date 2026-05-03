"""Official Python SDK for the HumanTone API.

`AsyncHumanTone` is lazy-imported via PEP 562 `__getattr__` so the package
remains usable without the optional `httpx` dependency. Sync users who run
`pip install humantone-sdk` (without the `[async]` extra) can `from
humantone import HumanTone` without triggering an `httpx` import.
"""

from typing import Any

from humantone._version import __version__
from humantone.client import HumanTone
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


def __getattr__(name: str) -> Any:
    """Lazy import for AsyncHumanTone — only loaded when accessed.

    Requires the [async] extra: pip install 'humantone-sdk[async]'.
    """
    if name == "AsyncHumanTone":
        try:
            from humantone.async_client import AsyncHumanTone
        except ImportError as e:
            raise ImportError(
                "AsyncHumanTone requires httpx. Install with: pip install 'humantone-sdk[async]'"
            ) from e
        return AsyncHumanTone
    raise AttributeError(f"module 'humantone' has no attribute {name!r}")


def __dir__() -> list[str]:
    """Expose lazy-loaded names (e.g. AsyncHumanTone) via `dir(humantone)` and IDE autocomplete."""
    return sorted(__all__)


__all__ = [
    "APIError",
    "AccountInfo",
    "AsyncHumanTone",
    "AuthenticationError",
    "Credits",
    "DailyLimitExceededError",
    "DetectResult",
    "HumanTone",
    "HumanToneError",
    "HumanizationLevel",
    "HumanizeResult",
    "InsufficientCreditsError",
    "InvalidRequestError",
    "NetworkError",
    "NotFoundError",
    "OutputFormat",
    "PermissionError",
    "Plan",
    "RateLimitError",
    "Subscription",
    "TimeoutError",
    "__version__",
]
