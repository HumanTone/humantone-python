"""Asynchronous HumanTone client (§7.7).

Importing this module triggers `import httpx` at module level. The package
`__init__.py` only imports it lazily through `__getattr__`, so users
without the `[async]` extra never reach this code.
"""

from __future__ import annotations

import os
import re
from types import TracebackType
from typing import Any, Literal

import httpx

from humantone._async_http import AsyncHttpTransport
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


class AsyncAccountResource:
    """Namespace for `await client.account.get()`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._transport = transport

    async def get(self) -> AccountInfo:
        return await self._transport.get_account()


class AsyncHumanTone:
    """Asynchronous mirror of `HumanTone`. Uses `httpx.AsyncClient`."""

    SDK_VERSION: str = _FALLBACK_VERSION

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        retry_on_post: bool = False,
        http_client: httpx.AsyncClient | None = None,
        user_agent: str | None = None,
    ) -> None:
        resolved_key = _resolve_setting(api_key, "HUMANTONE_API_KEY")
        if resolved_key is None:
            raise InvalidRequestError(
                "Missing API key. Pass api_key to AsyncHumanTone() or set the "
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
            self._http_client = httpx.AsyncClient()
            self._owns_http_client = True
        else:
            self._http_client = http_client
            self._owns_http_client = False

        self._transport = AsyncHttpTransport(
            api_key=resolved_key,
            base_url=resolved_base,
            user_agent=build_user_agent(user_agent),
            http_client=self._http_client,
            timeout=timeout,
            retry_policy=RetryPolicy(max_retries=max_retries, retry_on_post=retry_on_post),
        )
        self._account = AsyncAccountResource(self._transport)

    async def humanize(
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
        return await self._transport.humanize(body)

    async def detect(self, text: str) -> DetectResult:
        return await self._transport.detect({"content": text})

    @property
    def account(self) -> AsyncAccountResource:
        return self._account

    async def close(self) -> None:
        if self._owns_http_client:
            await self._transport.aclose()

    async def __aenter__(self) -> AsyncHumanTone:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


__all__ = ["AsyncAccountResource", "AsyncHumanTone"]
