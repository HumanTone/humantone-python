"""Response DTOs and enums for the HumanTone SDK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class HumanizationLevel(str, Enum):
    """Humanization aggressiveness for /v1/humanize.

    `advanced` and `extreme` are English-only; the API rejects them on
    non-English inputs with `language_not_supported`.
    """

    STANDARD = "standard"
    ADVANCED = "advanced"
    EXTREME = "extreme"


class OutputFormat(str, Enum):
    """Output rendering format returned by /v1/humanize."""

    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class HumanizeResult:
    """Successful response from /v1/humanize.

    `text` is mapped from the API's `content` field — a deliberate rename so
    Python callers don't shadow the loaded word "content".
    """

    text: str
    output_format: OutputFormat
    credits_used: int
    request_id: str | None


@dataclass(frozen=True, slots=True)
class DetectResult:
    """Successful response from /v1/detect."""

    ai_score: int
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    """Plan portion of /v1/account."""

    id: str
    name: str
    max_words: int
    monthly_credits: int
    api_access: bool


@dataclass(frozen=True, slots=True)
class Credits:
    """Credit-balance portion of /v1/account."""

    trial: int
    subscription: int
    extra: int
    total: int


@dataclass(frozen=True, slots=True)
class Subscription:
    """Subscription portion of /v1/account.

    `expires_at` is a `datetime` with `tzinfo=UTC` if the API returned an
    ISO 8601 string; `None` if the field was absent or null.
    """

    active: bool
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Successful response from /v1/account."""

    plan: Plan
    credits: Credits
    subscription: Subscription
    request_id: str | None = None
