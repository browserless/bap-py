import asyncio
import json
from typing import cast

import pytest

from browserless_bap.browserless import Browserless
from browserless_bap.errors import ConnectionError, ValueError
from browserless_bap.page import Page
from browserless_bap.transport import TransportFactory, TransportHandlers


class FakeConnection:
    def __init__(self) -> None:
        self.handlers: TransportHandlers | None = None
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def bind(self, handlers: TransportHandlers) -> None:
        self.handlers = handlers

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True


def test_browser_requires_endpoint_or_transport() -> None:
    with pytest.raises(ValueError):
        Browserless.connect()


@pytest.mark.asyncio
async def test_browser_and_page_context_managers_close_everything() -> None:
    connections: list[FakeConnection] = []
    urls: list[str | None] = []

    def factory(url: str | None) -> FakeConnection:
        urls.append(url)
        connection = FakeConnection()
        connections.append(connection)
        return connection

    async with Browserless.connect(
        browser_ws_endpoint="ws://example.test/chromium/bql?foo=bar",
        token="secret value",
        transport=factory,
    ) as browser:
        async with browser.page() as page:
            assert not page.closed
            assert browser.get_pages() == [page]
        assert page.closed

    assert connections[0].closed
    endpoint = urls[0]
    assert endpoint is not None
    assert "token=secret+value" in endpoint
    assert browser.get_pages() == []


@pytest.mark.asyncio
async def test_new_page_closes_transport_if_browser_closes_during_connect() -> None:
    connection = FakeConnection()
    started = asyncio.Event()
    release = asyncio.Event()

    async def factory(_url: str | None) -> FakeConnection:
        started.set()
        await release.wait()
        return connection

    browser = Browserless.connect(transport=cast(TransportFactory, factory))
    task = asyncio.create_task(browser.new_page())
    await started.wait()
    await browser.close()
    release.set()

    with pytest.raises(ValueError, match="Browser is closed"):
        await task
    assert connection.closed
    assert browser.get_pages() == []


@pytest.mark.asyncio
async def test_browser_close_logs_page_close_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingPage:
        closed = False

        async def close(self) -> None:
            raise RuntimeError("page close failed")

    browser = Browserless.connect(
        transport=cast(TransportFactory, lambda _url: FakeConnection())
    )
    browser._pages.append(cast(Page, FailingPage()))
    caplog.set_level("ERROR", logger="browserless_bap")

    await browser.close()

    assert "Failed to close a bap page" in caplog.text
    assert "page close failed" in caplog.text


@pytest.mark.asyncio
async def test_new_page_prunes_closed_pages() -> None:
    browser = Browserless.connect(
        transport=cast(TransportFactory, lambda _url: FakeConnection())
    )
    first = await browser.new_page()
    await first.close()

    second = await browser.new_page()

    assert browser._pages == [second]
    await browser.close()


@pytest.mark.parametrize("failure", ["cancel", "send", "timeout", "bind"])
async def test_new_page_closes_failed_connection(failure: str) -> None:
    class BrokenConnection(FakeConnection):
        def bind(self, handlers: TransportHandlers) -> None:
            super().bind(handlers)
            if failure == "bind":
                raise RuntimeError("cannot bind")

        async def send(self, message: str) -> None:
            if failure == "send":
                raise OSError("socket gone")
            await asyncio.Event().wait()

    connection = BrokenConnection()
    browser = Browserless.connect(
        transport=lambda _url: connection,
        connect_timeout=20 if failure == "timeout" else 0,
    )
    with pytest.raises(
        TimeoutError if failure in {"cancel", "timeout"} else ConnectionError
    ):
        await asyncio.wait_for(browser.new_page(), 0.1)
    assert connection.closed
    assert browser.get_pages() == []
    await browser.close()
