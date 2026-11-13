from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import pytest
from pytest import CaptureFixture

import browserless_bap as bap
import browserless_bap.sync_api as bap_sync

from .config import LiveConfig, assert_secret_absent

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXAMPLE_URL = "https://example.com"
INVALID_TOKEN = "bap-py-e2e-invalid-token"
MALFORMED_ENDPOINT_TOKEN = "bap-py-e2e-malformed-endpoint-token"


async def run_async_happy_path(config: LiveConfig) -> None:
    browser = bap.Browserless.connect(
        browser_ws_endpoint=config.url,
        token=config.token,
        timeout=config.timeout_ms,
    )
    async with browser:
        async with browser.page() as page:
            response = await page.goto(EXAMPLE_URL, timeout=config.timeout_ms)
            assert isinstance(response, Mapping)
            assert response.get("status") == 200
            assert await page.title() == "Example Domain"
            assert (await page.url()).startswith(EXAMPLE_URL)
            assert "Example Domain" in await page.content()
            assert await page.evaluate("1 + 1") in {"2", "2.0"}
            assert (await page.screenshot()).startswith(PNG_SIGNATURE)


def run_sync_happy_path(config: LiveConfig) -> None:
    sync_browserless = cast(Any, bap_sync.Browserless)
    with sync_browserless.connect(
        browser_ws_endpoint=config.url,
        token=config.token,
        timeout=config.timeout_ms,
    ) as browser:
        with browser.page() as page:
            response = page.goto(EXAMPLE_URL, timeout=config.timeout_ms)
            assert isinstance(response, Mapping)
            assert response.get("status") == 200
            assert page.title() == "Example Domain"
            assert page.url().startswith(EXAMPLE_URL)
            assert "Example Domain" in page.content()
            assert page.evaluate("1 + 1") in {"2", "2.0"}
            assert page.screenshot().startswith(PNG_SIGNATURE)


async def rejected_async_connection(
    url: str,
    token: str | None,
    timeout_ms: float,
) -> None:
    browser = bap.Browserless.connect(
        browser_ws_endpoint=url,
        token=token,
        timeout=timeout_ms,
    )
    async with browser:
        async with browser.page() as page:
            await page.title()


def rejected_sync_connection(
    url: str,
    token: str | None,
    timeout_ms: float,
) -> None:
    sync_browserless = cast(Any, bap_sync.Browserless)
    with sync_browserless.connect(
        browser_ws_endpoint=url,
        token=token,
        timeout=timeout_ms,
    ) as browser:
        with browser.page() as page:
            page.title()


@pytest.mark.e2e
def test_async_then_sync_happy_paths(
    live_config: LiveConfig,
    capsys: CaptureFixture[str],
) -> None:
    asyncio.run(run_async_happy_path(live_config))
    run_sync_happy_path(live_config)

    captured = capsys.readouterr()
    assert_secret_absent(live_config.token, [captured.out, captured.err])


@pytest.mark.e2e
async def test_missing_selector_preserves_server_timeout_error(
    live_config: LiveConfig,
    capsys: CaptureFixture[str],
) -> None:
    async with bap.Browserless.connect(
        browser_ws_endpoint=live_config.url,
        token=live_config.token,
        timeout=live_config.timeout_ms,
    ) as browser:
        async with browser.page() as page:
            await page.goto(EXAMPLE_URL, timeout=live_config.timeout_ms)
            with pytest.raises(bap.BrowserQLError, match="1500ms") as error:
                await page.wait_for_selector("#bap-py-missing-selector", timeout=1500)

    captured = capsys.readouterr()
    assert_secret_absent(
        live_config.token,
        [error.value, repr(error.value), captured.out, captured.err],
    )


@pytest.mark.e2e
@pytest.mark.parametrize("token", [None, INVALID_TOKEN], ids=["missing", "invalid"])
def test_missing_and_invalid_auth_are_typed_and_redacted(
    live_config: LiveConfig,
    capsys: CaptureFixture[str],
    token: str | None,
) -> None:
    with pytest.raises(bap.ConnectionError) as async_error:
        asyncio.run(
            rejected_async_connection(
                live_config.url,
                token,
                live_config.timeout_ms,
            )
        )
    with pytest.raises(bap.ConnectionError) as sync_error:
        rejected_sync_connection(
            live_config.url,
            token,
            live_config.timeout_ms,
        )

    captured = capsys.readouterr()
    values = [
        async_error.value,
        repr(async_error.value),
        sync_error.value,
        repr(sync_error.value),
        captured.out,
        captured.err,
    ]
    assert_secret_absent(live_config.token, values)
    if token is not None:
        assert_secret_absent(token, values)


@pytest.mark.e2e
def test_malformed_endpoint_is_typed_and_redacted(
    live_config: LiveConfig,
    capsys: CaptureFixture[str],
) -> None:
    malformed_url = f"http://bql.invalid/chromium/bql?token={MALFORMED_ENDPOINT_TOKEN}"
    with pytest.raises(bap.ConnectionError) as async_error:
        asyncio.run(
            rejected_async_connection(
                malformed_url,
                live_config.token,
                live_config.timeout_ms,
            )
        )
    with pytest.raises(bap.ConnectionError) as sync_error:
        rejected_sync_connection(
            malformed_url,
            live_config.token,
            live_config.timeout_ms,
        )

    captured = capsys.readouterr()
    values = [
        async_error.value,
        repr(async_error.value),
        sync_error.value,
        repr(sync_error.value),
        captured.out,
        captured.err,
    ]
    assert_secret_absent(live_config.token, values)
    assert_secret_absent(MALFORMED_ENDPOINT_TOKEN, values)
