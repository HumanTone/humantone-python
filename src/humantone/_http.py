"""Synchronous HTTP transport built on `requests` (§7.6.1)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

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
_sleep = time.sleep


class HttpTransport:
    """Owns the requests Session and runs the retry loop around every call.

    `http_client` is typed as `requests.Session` for mypy-friendliness, but
    we only rely on `.request(method, url, ...) -> requests.Response` and
    `.close()`. Callers passing a duck-typed object should suppress the
    type warning at the boundary in `client.py` (which accepts `Any`).
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        user_agent: str,
        http_client: requests.Session,
        timeout: float,
        retry_policy: RetryPolicy,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._http_client = http_client
        self._timeout = timeout
        self._retry_policy = retry_policy

    def humanize(self, body: dict[str, Any]) -> HumanizeResult:
        result = self._request("POST", "/v1/humanize", endpoint="humanize", json_body=body)
        assert isinstance(result, HumanizeResult)
        return result

    def detect(self, body: dict[str, Any]) -> DetectResult:
        result = self._request("POST", "/v1/detect", endpoint="detect", json_body=body)
        assert isinstance(result, DetectResult)
        return result

    def get_account(self) -> AccountInfo:
        result = self._request("GET", "/v1/account", endpoint="account", json_body=None)
        assert isinstance(result, AccountInfo)
        return result

    def close(self) -> None:
        self._http_client.close()

    def _build_headers(self, has_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(
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
                response = self._http_client.request(
                    method,
                    url,
                    headers=dict(headers),
                    json=json_body,
                    timeout=self._timeout,
                )
            except requests.exceptions.Timeout as e:
                exception = TimeoutError(
                    "Request timed out",
                    status_code=None,
                    error_code="timeout",
                    retryable=False,
                    details={"underlying": str(e)},
                )
            except requests.exceptions.ConnectionError as e:
                exception = NetworkError(
                    "Network error contacting HumanTone API",
                    status_code=None,
                    error_code="network_error",
                    retryable=True,
                    details={"underlying": str(e)},
                )
            except requests.exceptions.RequestException as e:
                exception = NetworkError(
                    "Transport error contacting HumanTone API",
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
                _sleep(delay)
                attempt += 1
                continue

            raise exception


__all__ = ["HttpTransport"]
