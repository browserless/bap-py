from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from pytest import CaptureFixture

import browserless_bap as bap
import browserless_bap.sync_api as bap_sync
from browserless_bap.errors import BrowserQLError

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
    with bap_sync.Browserless.connect(
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
    with bap_sync.Browserless.connect(
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
async def test_element_handle_scoping_and_selector_encoding(
    live_config: LiveConfig,
) -> None:
    async with bap.Browserless.connect(
        browser_ws_endpoint=live_config.url,
        token=live_config.token,
        timeout=live_config.timeout_ms,
    ) as browser:
        async with browser.page() as page:
            await page.set_content(
                '<ul id="list"><li>a</li><li>b</li><li>c</li></ul>'
                '<div id="box"><span data-q=\'a"b\'>QUOTE</span>'
                "<span id=\"a:b\">COLON</span><span data-q='x\\y'>BSLATTR</span>"
                '<span class="n">NEWLINE</span><span class="plain">PLAIN</span></div>'
                "<span data-q='a\"b'>OUTSIDE</span>"
            )
            ul = await page.query_selector("ul")
            assert ul is not None
            assert [
                await li.text_content() for li in await ul.query_selector_all("li")
            ] == ["a", "b", "c"]
            indexed_ul = (await page.query_selector_all("ul"))[0]
            assert [
                await li.text_content()
                for li in await indexed_ul.query_selector_all("li")
            ] == ["a", "b", "c"]
            first = await indexed_ul.query_selector("li")
            assert first is not None
            assert await first.text_content() == "a"
            body = await page.query_selector("body")
            assert body is not None
            nested_ul = (await body.query_selector_all("ul"))[0]
            items = await nested_ul.query_selector_all("li")
            assert [await li.text_content() for li in items] == ["a", "b", "c"]
            assert await items[1].click() is not None

            box = await page.query_selector("#box")
            assert box is not None
            for selector, expected in [
                ("[data-q='a\"b']", "QUOTE"),
                ("#a\\:b", "COLON"),
                ('[data-q="x\\\\y"]', "BSLATTR"),
                (".n,\n.nomatch", "NEWLINE"),
                ("span.plain", "PLAIN"),
            ]:
                match = await box.query_selector(selector)
                assert match is not None
                assert await match.text_content() == expected
                matches = await box.query_selector_all(selector)
                assert [await match.text_content() for match in matches] == [expected]
            quotes = await page.query_selector_all("[data-q='a\"b']")
            assert len(quotes) == 2
            assert await quotes[0].text_content() == "QUOTE"
            visible = await ul.query_selector_all("li", timeout=5000, visible=True)
            assert [await li.text_content() for li in visible] == ["a", "b", "c"]
            assert await ul.query_selector("p") is None
            assert await ul.query_selector_all("p") == []


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
    with pytest.raises(bap.BAPConnectionError) as async_error:
        asyncio.run(
            rejected_async_connection(
                live_config.url,
                token,
                live_config.timeout_ms,
            )
        )
    with pytest.raises(bap.BAPConnectionError) as sync_error:
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
    with pytest.raises(bap.BAPConnectionError) as async_error:
        asyncio.run(
            rejected_async_connection(
                malformed_url,
                live_config.token,
                live_config.timeout_ms,
            )
        )
    with pytest.raises(bap.BAPConnectionError) as sync_error:
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


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_opt_in_fields_live(
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
            responses = await page.response(type=["document"])
            assert responses
            assert all("body" not in item for item in responses)
            with_bodies = await page.response(type=["document"], body=True)
            assert any(
                "Example Domain" in (item.get("body") or "") for item in with_bodies
            )
            await page.set_content('<h1 id="t">Hello <b>opt</b>-in</h1>')
            plain = await page.query_selector("h1")
            assert plain is not None
            with pytest.raises(bap.BAPValueError, match="html=True"):
                _ = plain.inner_html
            assert plain.child_element_count == 1
            assert isinstance(plain.child_element_count, int)
            html = await page.query_selector("h1", html=True)
            assert html is not None
            assert html.inner_html == "Hello <b>opt</b>-in"
            assert (html.outer_html or "").startswith("<h1")
            child = await plain.query_selector(
                "b", timeout=2000, visible=True, html=True
            )
            assert child is not None
            assert child.inner_html == "opt"
            children = await plain.query_selector_all(
                "b", timeout=2000, visible=True, html=True
            )
            assert [item.outer_html for item in children] == ["<b>opt</b>"]
    captured = capsys.readouterr()
    assert_secret_absent(live_config.token, [captured.out, captured.err])


@pytest.mark.e2e
async def test_wait_for_function_promise_flag_waits_for_plain_predicate(
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
            with pytest.raises(BrowserQLError) as error:
                await page.wait_for_function(
                    "() => window.__bapNeverReady === true",
                    timeout=1500,
                    complete_on_promise_resolution=True,
                )
            result = await page.wait_for_function(
                "async () => { await new Promise(r => setTimeout(r, 100)); "
                "return false; }",
                timeout=3000,
                complete_on_promise_resolution=True,
            )
            assert "time" in result

    captured = capsys.readouterr()
    assert_secret_absent(live_config.token, [error.value, captured.out, captured.err])
