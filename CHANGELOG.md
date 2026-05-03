# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - Unreleased

### Added

- Initial release of the official HumanTone Python SDK.
- Synchronous `HumanTone` client with three endpoint methods:
  `humanize(text, *, level, output_format, custom_instructions)`,
  `detect(text)`, and `account.get()`.
- Optional asynchronous `AsyncHumanTone` client (install with
  `pip install "humantone-sdk[async]"`).
- Full typed exception hierarchy under `HumanToneError` covering
  authentication, permission, rate-limit, insufficient credits, daily-limit,
  invalid-request, not-found, API, timeout, and network errors.
- Configurable retry policy with exponential backoff and jitter; honors the
  `Retry-After` header in numeric and HTTP-date forms. POST methods do not
  retry on network/5xx by default to avoid double-billing on `humanize`.
- Configurable HTTP client injection (`requests.Session`-compatible for sync,
  `httpx.AsyncClient` for async).
- Configurable timeout, base URL, and User-Agent suffix.
- Reads `HUMANTONE_API_KEY` and `HUMANTONE_BASE_URL` from environment.
- Eager API-key validation in the constructor.
- PEP 561 type marker (`py.typed`) for downstream type-checking.
