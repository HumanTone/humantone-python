# humantone-sdk

Official Python SDK for [HumanTone](https://humantone.io). Humanize AI-generated text and check AI likelihood from your Python code. One API key, same credits you already use in the HumanTone web app.

[![PyPI version](https://img.shields.io/pypi/v/humantone-sdk.svg)](https://pypi.org/project/humantone-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/humantone-sdk.svg)](https://pypi.org/project/humantone-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Note on the package name:** the canonical name `humantone` on PyPI is currently held by an unrelated abandoned package. We publish under `humantone-sdk` for now and import as `import humantone`. After we recover the canonical name, `humantone-sdk` will continue to work as a deprecated alias.

## Install

```bash
pip install humantone-sdk
```

For the async client (uses `httpx`):

```bash
pip install "humantone-sdk[async]"
```

Requires Python 3.10 or later.

## Quickstart

```python
import os
from humantone import HumanTone

client = HumanTone(api_key=os.environ["HUMANTONE_API_KEY"])

result = client.humanize(
    text="Your AI-generated draft goes here. Must be at least 30 words for the API to accept it.",
)

print(result.text)
print(f"Credits used: {result.credits_used}")
```

The client also picks up `HUMANTONE_API_KEY` from the environment automatically:

```python
client = HumanTone()
```

## API

### `client.humanize(text, *, level, output_format, custom_instructions)`

Rewrites AI-generated text to sound more natural.

| Argument | Type | Default | Notes |
|---|---|---|---|
| `text` | `str` | required | Min 30 words. Max depends on plan (Basic 750, Standard 1000, Pro 1500). |
| `level` | `HumanizationLevel` or `"standard" \| "advanced" \| "extreme"` | `"standard"` | `advanced` and `extreme` are English-only. |
| `output_format` | `OutputFormat` or `"text" \| "html" \| "markdown"` | `"text"` | SDK default is `"text"` even though the API default is `"html"`. |
| `custom_instructions` | `str \| None` | `None` | Free-form rewrite guidance. Max 1000 chars. |

Returns `HumanizeResult` with `text: str`, `output_format: OutputFormat`, `credits_used: int`, `request_id: str | None`.

### `client.detect(text)`

Returns AI likelihood score 0-100. Free, but limited to 30 calls per day per account (shared between the web app and the API).

```python
score = client.detect(text="...")
print(score.ai_score)   # 0-100
```

### `client.account.get()`

Returns plan, credit balance, and subscription status.

```python
info = client.account.get()
print(info.plan.name)
print(info.credits.total)
print(info.plan.max_words)
print(info.subscription.active)
print(info.subscription.expires_at)  # datetime | None
```

## Configuration

```python
client = HumanTone(
    api_key="ht_...",                     # or HUMANTONE_API_KEY env
    base_url="https://api.humantone.io",  # or HUMANTONE_BASE_URL env, default is api.humantone.io
    timeout=120.0,                         # seconds
    max_retries=2,
    retry_on_post=False,                   # POST endpoints retry only when explicit
    user_agent="my-app/1.0",               # appended to default UA after a single space
)
```

You can inject any `requests.Session`-compatible HTTP client:

```python
import requests
from humantone import HumanTone

session = requests.Session()
session.proxies = {"https": "http://proxy.internal:8080"}

client = HumanTone(api_key="ht_...", http_client=session)
```

## Error handling

All errors raised by the SDK extend `HumanToneError`.

```python
from humantone import (
    HumanTone,
    HumanToneError,
    InsufficientCreditsError,
    DailyLimitExceededError,
    InvalidRequestError,
    AuthenticationError,
    RateLimitError,
)

client = HumanTone()

try:
    result = client.humanize(text="...")
except InsufficientCreditsError:
    print("Buy more credits at https://app.humantone.io/settings/credits")
except RateLimitError as e:
    print(f"Rate limited. Retry in {e.retry_after_seconds}s.")
except InvalidRequestError as e:
    print(f"Bad input: {e}")
except AuthenticationError:
    print("Check your API key.")
except HumanToneError as e:
    print(f"HumanTone API error ({e.error_code}): {e}")
    if e.request_id:
        print(f"Request ID: {e.request_id}")
```

Every error exposes:

- `e.message: str` (use `str(e)`)
- `e.status_code: int | None`
- `e.request_id: str | None`
- `e.error_code: str | None`
- `e.details: dict | None`
- `e.retryable: bool`

Specific exceptions add typed accessors: `RateLimitError.retry_after_seconds: int`, `DailyLimitExceededError.time_to_next_renew: int | None`, `InsufficientCreditsError.required_credits: int | None` and `available_credits: int | None`.

> Python's stdlib has a builtin `TimeoutError`. The SDK's `humantone.TimeoutError` shadows it inside the `humantone` namespace. Use `from humantone import TimeoutError as HumanToneTimeoutError` if you need to disambiguate.

## Retry behavior

The SDK retries `account.get()` on network errors, 5xx, and 429 (up to 2 retries). POST methods (`humanize`, `detect`) do **not** retry on network or 5xx by default. Humanize debits credits, so a retried request risks double-billing. Pass `retry_on_post=True` to opt in. 429 always retries on every method.

`Retry-After` headers are honored in both numeric (seconds) and HTTP-date formats.

## Async usage

```python
import asyncio
from humantone import AsyncHumanTone

async def main():
    async with AsyncHumanTone() as client:
        result = await client.humanize(text="...")
        print(result.text)

asyncio.run(main())
```

The async client uses `httpx` and is exposed via `pip install "humantone-sdk[async]"`.

## Limits to remember

- **Per-request word limit.** Basic 750, Standard 1000, Pro 1500. Inputs must be at least 30 words.
- **Credits.** Humanize consumes 1 credit per 100 words. Account checks and AI likelihood checks do not consume credits.
- **AI likelihood quota.** 30 checks per day per account, shared between the HumanTone web app and any API or SDK usage. Resets at midnight UTC.
- **API access.** Included on all paid plans. Free trial accounts cannot use the API.

## Get an API key

Sign up at [humantone.io](https://humantone.io). The HumanTone API is paid only.

## License

MIT

## Links

- API docs: https://humantone.io/docs/api/
- MCP server: https://humantone.io/docs/mcp/
- Issues: https://github.com/humantone/humantone-python/issues
- Support: help@humantone.io
