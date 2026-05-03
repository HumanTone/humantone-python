"""End-to-end tests for `AsyncHumanTone` using `respx`."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from humantone import (
    APIError,
    AsyncHumanTone,
    DailyLimitExceededError,
    HumanizationLevel,
    HumanizeResult,
    InsufficientCreditsError,
    InvalidRequestError,
    NetworkError,
    OutputFormat,
    RateLimitError,
)
from humantone import TimeoutError as HTTimeout

VALID_KEY = "ht_" + "a" * 64
BASE_URL = "https://api.test.local"


@pytest.fixture(autouse=True)
def _no_async_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace async transport sleep so retry tests are fast."""
    import humantone._async_http

    async def _zero(_seconds: float) -> None:
        return None

    monkeypatch.setattr(humantone._async_http, "_async_sleep", _zero)


def _client(**kw: object) -> AsyncHumanTone:
    return AsyncHumanTone(api_key=VALID_KEY, base_url=BASE_URL, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


async def test_missing_api_key_raises() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        AsyncHumanTone()
    assert excinfo.value.error_code == "missing_api_key"


async def test_malformed_api_key_raises() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        AsyncHumanTone(api_key="not-a-key", base_url=BASE_URL)
    assert excinfo.value.error_code == "invalid_api_key_format"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@respx.mock
async def test_humanize_happy_path() -> None:
    respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "rid-1",
                "content": "humanized",
                "output_format": "text",
                "credits_used": 3,
            },
        )
    )
    async with _client() as client:
        result = await client.humanize(text="anything")
    assert isinstance(result, HumanizeResult)
    assert result.text == "humanized"


@respx.mock
async def test_detect_happy_path() -> None:
    respx.post(f"{BASE_URL}/v1/detect").mock(
        return_value=httpx.Response(200, json={"success": True, "ai_score": 73})
    )
    async with _client() as client:
        r = await client.detect(text="anything")
    assert r.ai_score == 73


@respx.mock
async def test_account_happy_path() -> None:
    respx.get(f"{BASE_URL}/v1/account").mock(
        return_value=httpx.Response(
            200,
            json={
                "plan": {
                    "id": "pro",
                    "name": "Pro",
                    "max_words": 1500,
                    "monthly_credits": 1000,
                    "api_access": True,
                },
                "credits": {
                    "trial": 0,
                    "subscription": 820,
                    "extra": 150,
                    "total": 970,
                },
                "subscription": {
                    "active": True,
                    "expires_at": "2026-05-08T00:00:00.000Z",
                },
            },
        )
    )
    async with _client() as client:
        info = await client.account.get()
    assert info.plan.name == "Pro"


# ---------------------------------------------------------------------------
# Request body & headers
# ---------------------------------------------------------------------------


@respx.mock
async def test_humanize_default_output_format_is_text() -> None:
    route = respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "x",
                "content": "y",
                "output_format": "text",
                "credits_used": 1,
            },
        )
    )
    async with _client() as client:
        await client.humanize(text="x")
    sent = json.loads(route.calls[0].request.content.decode())
    assert sent["output_format"] == "text"


@respx.mock
async def test_humanize_full_body() -> None:
    route = respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "x",
                "content": "y",
                "output_format": "html",
                "credits_used": 1,
            },
        )
    )
    async with _client() as client:
        await client.humanize(
            text="my-draft",
            level=HumanizationLevel.ADVANCED,
            output_format=OutputFormat.HTML,
            custom_instructions="be terse",
        )
    sent = json.loads(route.calls[0].request.content.decode())
    assert sent == {
        "content": "my-draft",
        "humanization_level": "advanced",
        "output_format": "html",
        "custom_instructions": "be terse",
    }


@respx.mock
async def test_authorization_bearer_header_sent() -> None:
    route = respx.get(f"{BASE_URL}/v1/account").mock(
        return_value=httpx.Response(
            200,
            json={
                "plan": {
                    "id": "p",
                    "name": "P",
                    "max_words": 100,
                    "monthly_credits": 10,
                    "api_access": True,
                },
                "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
                "subscription": {"active": True, "expires_at": None},
            },
        )
    )
    async with _client() as client:
        await client.account.get()
    headers = route.calls[0].request.headers
    assert headers["Authorization"] == f"Bearer {VALID_KEY}"
    assert headers["Accept"] == "application/json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@respx.mock
async def test_400_not_enough_credits() -> None:
    respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(400, json={"error": "Not enough credits"})
    )
    async with _client() as client:
        with pytest.raises(InsufficientCreditsError):
            await client.humanize(text="x")


@respx.mock
async def test_429_with_retry_after() -> None:
    # 429 always retries on POST. Mock 3 in a row.
    respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(429, json={"error": "rate"}, headers={"Retry-After": "1"})
    )
    async with _client() as client:
        with pytest.raises(RateLimitError) as excinfo:
            await client.humanize(text="x")
    assert excinfo.value.retry_after_seconds == 1


@respx.mock
async def test_detect_daily_limit() -> None:
    respx.post(f"{BASE_URL}/v1/detect").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": False,
                "error": "Daily usage limit reached. ...",
                "time_to_next_renew": 60,
            },
        )
    )
    async with _client() as client:
        with pytest.raises(DailyLimitExceededError) as excinfo:
            await client.detect(text="x")
    assert excinfo.value.time_to_next_renew == 60


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_account_retries_500_then_succeeds() -> None:
    success_body = {
        "plan": {
            "id": "p",
            "name": "P",
            "max_words": 100,
            "monthly_credits": 10,
            "api_access": True,
        },
        "credits": {"trial": 0, "subscription": 0, "extra": 0, "total": 0},
        "subscription": {"active": True, "expires_at": None},
    }
    respx.get(f"{BASE_URL}/v1/account").mock(
        side_effect=[
            httpx.Response(500, json={"error": "x"}),
            httpx.Response(500, json={"error": "x"}),
            httpx.Response(200, json=success_body),
        ]
    )
    async with _client() as client:
        info = await client.account.get()
    assert info.plan.id == "p"


@respx.mock
async def test_humanize_500_does_not_retry_by_default() -> None:
    route = respx.post(f"{BASE_URL}/v1/humanize").mock(
        return_value=httpx.Response(500, json={"error": "x"})
    )
    async with _client() as client:
        with pytest.raises(APIError):
            await client.humanize(text="x")
    assert route.call_count == 1


@respx.mock
async def test_humanize_500_retries_with_retry_on_post() -> None:
    success_body = {
        "success": True,
        "request_id": "x",
        "content": "y",
        "output_format": "text",
        "credits_used": 1,
    }
    respx.post(f"{BASE_URL}/v1/humanize").mock(
        side_effect=[
            httpx.Response(500, json={"error": "x"}),
            httpx.Response(500, json={"error": "x"}),
            httpx.Response(200, json=success_body),
        ]
    )
    async with _client(retry_on_post=True) as client:
        result = await client.humanize(text="x")
    assert isinstance(result, HumanizeResult)


@respx.mock
async def test_network_error_maps_to_network_error() -> None:
    respx.get(f"{BASE_URL}/v1/account").mock(side_effect=httpx.ConnectError("simulated"))
    async with _client() as client:
        with pytest.raises(NetworkError):
            await client.account.get()


@respx.mock
async def test_timeout_maps_to_timeout_error() -> None:
    route = respx.post(f"{BASE_URL}/v1/humanize").mock(side_effect=httpx.ReadTimeout("simulated"))
    async with _client() as client:
        with pytest.raises(HTTimeout):
            await client.humanize(text="x")
    assert route.call_count == 1  # timeout never retries


# ---------------------------------------------------------------------------
# Async context manager closes owned client
# ---------------------------------------------------------------------------


async def test_async_context_manager_closes_owned_client() -> None:
    closed = {"v": False}

    async def _wrapped() -> None:
        client = AsyncHumanTone(api_key=VALID_KEY, base_url=BASE_URL)
        original = client._http_client.aclose

        async def _track() -> None:
            closed["v"] = True
            await original()

        client._http_client.aclose = _track  # type: ignore[method-assign]
        async with client:
            pass

    await _wrapped()
    assert closed["v"] is True


async def test_close_is_no_op_for_injected_async_client() -> None:
    client_obj = httpx.AsyncClient()
    closed = {"v": False}

    original = client_obj.aclose

    async def _track() -> None:
        closed["v"] = True
        await original()

    client_obj.aclose = _track  # type: ignore[method-assign]
    client = AsyncHumanTone(api_key=VALID_KEY, base_url=BASE_URL, http_client=client_obj)
    await client.close()
    assert closed["v"] is False
    await client_obj.aclose()
