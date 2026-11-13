from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .config import (
    DEFAULT_BROWSERLESS_URL,
    ConfigurationError,
    LiveConfig,
    assert_secret_absent,
    load_live_config,
)


def test_missing_token_leaves_live_suite_unconfigured() -> None:
    assert load_live_config({}) is None


@pytest.mark.parametrize(
    "token",
    ["invalid", "YOUR_API_TOKEN_HERE", "changeme"],
)
def test_placeholder_tokens_are_rejected(token: str) -> None:
    with pytest.raises(ConfigurationError, match="real Browserless API token"):
        load_live_config({"BROWSERLESS_TOKEN": token})


def test_default_endpoint_is_the_public_cloud() -> None:
    token = "live-token-value"
    config = load_live_config({"BROWSERLESS_TOKEN": token})

    assert config == LiveConfig(
        url="wss://production-sfo.browserless.io/chromium/bql",
        token=token,
    )


def test_custom_endpoint_is_honoured() -> None:
    url = "ws://localhost:3000/chromium/bql"
    config = load_live_config(
        {"BROWSERLESS_TOKEN": "live-token-value", "BROWSERLESS_URL": url}
    )

    assert config is not None
    assert config.url == url


def test_blank_url_falls_back_to_default() -> None:
    config = load_live_config(
        {"BROWSERLESS_TOKEN": "live-token-value", "BROWSERLESS_URL": "  "}
    )

    assert config is not None
    assert config.url == DEFAULT_BROWSERLESS_URL


def test_non_websocket_endpoint_is_rejected_without_echoing_secrets() -> None:
    token = "do-not-render-this-token"
    with pytest.raises(ConfigurationError, match="ws:// or wss://") as caught:
        load_live_config(
            {
                "BROWSERLESS_TOKEN": token,
                "BROWSERLESS_URL": "https://example.com/chromium/bql?token=url-secret",
            }
        )

    assert token not in str(caught.value)
    assert "url-secret" not in str(caught.value)


def test_valid_configuration_redacts_token_from_repr() -> None:
    token = "live-token-value"
    config = load_live_config({"BROWSERLESS_TOKEN": token})

    assert config == LiveConfig(url=DEFAULT_BROWSERLESS_URL, token=token)
    assert token not in repr(config)


def test_endpoint_is_redacted_from_repr() -> None:
    config = load_live_config(
        {
            "BROWSERLESS_TOKEN": "live-token-value",
            "BROWSERLESS_URL": "wss://example.com/chromium/bql?token=url-secret",
        }
    )

    assert "url-secret" not in repr(config)


def test_secret_output_guard_has_a_generic_failure() -> None:
    token = "live-token-value"
    with pytest.raises(
        AssertionError,
        match="sensitive credential appeared in test output",
    ) as caught:
        assert_secret_absent(token, [f"request failed for ?token={token}"])

    assert token not in str(caught.value)


@pytest.mark.parametrize("selection", [[], ["-m", "not e2e_disabled"]])
def test_live_suite_needs_explicit_e2e_selection(selection: list[str]) -> None:
    # A token alone must not reach a live endpoint from a plain `pytest` run.
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "BROWSERLESS_TOKEN": "live-token-value",
        # Unreachable, so a regression fails instead of reaching a real service.
        "BROWSERLESS_URL": "ws://127.0.0.1:9/chromium/bql",
    }
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e/test_live.py",
            "-q",
            "-rs",
            *selection,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "7 skipped" in result.stdout
    assert "requires -m e2e" in result.stdout
