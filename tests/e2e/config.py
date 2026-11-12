"""Credential-safe configuration for the live BrowserQL suite."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_BROWSERLESS_URL = "wss://production-sfo.browserless.io/chromium/bql"
TOKEN_VARIABLE = "BROWSERLESS_TOKEN"
URL_VARIABLE = "BROWSERLESS_URL"

_PLACEHOLDER_TOKENS = {
    "changeme",
    "invalid",
    "replace-me",
    "token",
    "your-api-token",
    "your_api_token_here",
}


class ConfigurationError(ValueError):
    """The live environment is present but unsafe or incomplete."""


@dataclass(frozen=True)
class LiveConfig:
    # The URL may carry a token in its query string, so neither is rendered.
    url: str = field(repr=False)
    token: str = field(repr=False)
    timeout_ms: float = 90_000


def load_live_config(environment: Mapping[str, str]) -> LiveConfig | None:
    """Load the live-suite token and endpoint, or return None when no token is set."""

    token = environment.get(TOKEN_VARIABLE, "").strip()
    if not token:
        return None

    if token.lower() in _PLACEHOLDER_TOKENS:
        raise ConfigurationError(
            f"{TOKEN_VARIABLE} must be a real Browserless API token, not a placeholder"
        )

    url = environment.get(URL_VARIABLE, "").strip() or DEFAULT_BROWSERLESS_URL
    if urlsplit(url).scheme not in {"ws", "wss"}:
        # Never echo the URL: it may carry a token in its query string.
        raise ConfigurationError(
            f"{URL_VARIABLE} must be a ws:// or wss:// BrowserQL endpoint"
        )

    return LiveConfig(url=url, token=token)


def assert_secret_absent(secret: str, values: Sequence[object]) -> None:
    """Fail without echoing the credential when an output contains it."""

    if any(secret in str(value) for value in values):
        raise AssertionError("sensitive credential appeared in test output")
