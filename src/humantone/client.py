"""Synchronous HumanTone client (§6.3)."""

from __future__ import annotations

import os
import re
from types import TracebackType
from typing import Any, Literal

import requests

from humantone._http import HttpTransport
from humantone._retry import RetryPolicy
from humantone._user_agent import build_user_agent
from humantone._version import __version__ as _FALLBACK_VERSION  # noqa: N812
from humantone.errors import InvalidRequestError
from humantone.models import (
    AccountInfo,
    DetectResult,
    HumanizationLevel,
    HumanizeResult,
    OutputFormat,
)

_API_KEY_REGEX = re.compile(r"^ht_[0-9a-f]{64}$")
_DEFAULT_BASE_URL = "https://api.humantone.io"

LevelLike = HumanizationLevel | Literal["standard", "advanced", "extreme"]
FormatLike = OutputFormat | Literal["text", "html", "markdown"]


def _resolve_setting(arg_value: str | None, env_var: str) -> str | None:
    """Apply §5.2 precedence: constructor arg > env var > None.

    Empty / whitespace-only values (in either source) are treated as unset.
    """
    if arg_value is not None:
        cleaned = arg_value.strip()
        if cleaned:
            return cleaned
    env_value = os.environ.get(env_var, "")
    cleaned_env = env_value.strip()
    if cleaned_env:
        return cleaned_env
    return None


def _coerce_level(level: LevelLike) -> str:
    if isinstance(level, HumanizationLevel):
        return level.value
    return level


def _coerce_format(output_format: FormatLike) -> str:
    if isinstance(output_format, OutputFormat):
        return output_format.value
    return output_format


class AccountResource:
    """Namespace for `client.account.get()` (§6.3)."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def get(self) -> AccountInfo:
        return self._transport.get_account()


class HumanTone:
    """Official synchronous HumanTone client.

    Eagerly validates the API key in the constructor (§5.3) so misconfigured
    callers fail fast at startup rather than on first request.
    """

    SDK_VERSION: str = _FALLBACK_VERSION

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        retry_on_post: bool = False,
        http_client: Any = None,
        user_agent: str | None = None,
    ) -> None:
        resolved_key = _resolve_setting(api_key, "HUMANTONE_API_KEY")
        if resolved_key is None:
            raise InvalidRequestError(
                "Missing API key. Pass api_key to HumanTone() or set the "
                "HUMANTONE_API_KEY environment variable. Get a key at "
                "https://app.humantone.io/settings/api",
                error_code="missing_api_key",
            )
        if not _API_KEY_REGEX.match(resolved_key):
            raise InvalidRequestError(
                "Invalid API key format. Expected ht_ prefix followed by 64 hex characters.",
                error_code="invalid_api_key_format",
            )

        resolved_base = _resolve_setting(base_url, "HUMANTONE_BASE_URL") or _DEFAULT_BASE_URL

        if http_client is None:
            self._http_client = requests.Session()
            self._owns_http_client = True
        else:
            self._http_client = http_client
            self._owns_http_client = False

        self._transport = HttpTransport(
            api_key=resolved_key,
            base_url=resolved_base,
            user_agent=build_user_agent(user_agent),
            http_client=self._http_client,
            timeout=timeout,
            retry_policy=RetryPolicy(max_retries=max_retries, retry_on_post=retry_on_post),
        )
        self._account = AccountResource(self._transport)

    def humanize(
        self,
        text: str,
        *,
        level: LevelLike = HumanizationLevel.STANDARD,
        output_format: FormatLike = OutputFormat.TEXT,
        custom_instructions: str | None = None,
    ) -> HumanizeResult:
        body: dict[str, Any] = {
            "content": text,
            "humanization_level": _coerce_level(level),
            "output_format": _coerce_format(output_format),
        }
        if custom_instructions is not None:
            body["custom_instructions"] = custom_instructions
        return self._transport.humanize(body)

    def detect(self, text: str) -> DetectResult:
        return self._transport.detect({"content": text})

    @property
    def account(self) -> AccountResource:
        return self._account

    def close(self) -> None:
        """Close the underlying session if the SDK created it.

        No-op when the caller injected their own `http_client` — caller owns
        its lifecycle in that case.
        """
        if self._owns_http_client:
            self._transport.close()

    def __enter__(self) -> HumanTone:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


__all__ = ["AccountResource", "HumanTone"]
