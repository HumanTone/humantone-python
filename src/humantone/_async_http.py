"""Asynchronous HTTP transport built on `httpx` (§7.6.1).

This module imports `httpx` at module-level. It is only loaded through the
`humantone.__getattr__` lazy hook, so users who installed without the
`[async]` extra never trigger the import.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from humantone._retry import RetryPolicy, backoff_delay, should_retry
from humantone.errors import (
    HumanToneError,
    NetworkError,
    TimeoutError,
    parse_response,
)
from humantone.models import AccountInfo, DetectResult, HumanizeResult

_logger = logging.getLogger("humantone")

# Tests monkeypatch this to skip waiting in retry loops.
_async_sleep = asyncio.sleep


class AsyncHttpTransport:
    """Owns the httpx.AsyncClient and runs the async retry loop."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        user_agent: str,
        http_client: httpx.AsyncClient,
        timeout: float,
        retry_policy: RetryPolicy,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._http_client = http_client
        self._timeout_obj = httpx.Timeout(
            timeout,
            connect=timeout,
            read=timeout,
            write=timeout,
            pool=timeout,
        )
        self._retry_policy = retry_policy

    async def humanize(self, body: dict[str, Any]) -> HumanizeResult:
        result = await self._request("POST", "/v1/humanize", endpoint="humanize", json_body=body)
        assert isinstance(result, HumanizeResult)
        return result

    async def detect(self, body: dict[str, Any]) -> DetectResult:
        result = await self._request("POST", "/v1/detect", endpoint="detect", json_body=body)
        assert isinstance(result, DetectResult)
        return result

    async def get_account(self) -> AccountInfo:
        result = await self._request("GET", "/v1/account", endpoint="account", json_body=None)
        assert isinstance(result, AccountInfo)
        return result

    async def aclose(self) -> None:
        await self._http_client.aclose()

    def _build_headers(self, has_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str,
        json_body: dict[str, Any] | None,
    ) -> HumanizeResult | DetectResult | AccountInfo:
        url = f"{self._base_url}{path}"
        headers = self._build_headers(has_body=json_body is not None)

        attempt = 0
        while True:
            exception: HumanToneError
            try:
                response = await self._http_client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    timeout=self._timeout_obj,
                )
            except httpx.TimeoutException as e:
                exception = TimeoutError(
                    "Request timed out",
                    status_code=None,
                    error_code="timeout",
                    retryable=False,
                    details={"underlying": str(e)},
                )
            except httpx.RequestError as e:
                exception = NetworkError(
                    "Network error contacting HumanTone API",
                    status_code=None,
                    error_code="network_error",
                    retryable=True,
                    details={"underlying": str(e)},
                )
            else:
                try:
                    return parse_response(
                        status_code=response.status_code,
                        body_bytes=response.content,
                        headers=response.headers,
                        endpoint=endpoint,
                    )
                except HumanToneError as e:
                    exception = e

            if should_retry(
                policy=self._retry_policy,
                method=method,
                endpoint=endpoint,
                exception=exception,
                attempt=attempt,
            ):
                delay = backoff_delay(exception, attempt + 1)
                _logger.debug(
                    "Retrying %s %s after %.3fs (attempt %d/%d): %s",
                    method,
                    path,
                    delay,
                    attempt + 1,
                    self._retry_policy.max_retries,
                    type(exception).__name__,
                )
                await _async_sleep(delay)
                attempt += 1
                continue

            raise exception


__all__ = ["AsyncHttpTransport"]
