import asyncio
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from browserless_bap.page import Page
from browserless_bap.transport import (
    MessageListener,
    Subscriber,
    Transport,
    Unsubscribe,
)
from browserless_bap.types.responses import ConsoleMessage

# Polling is deliberate for observable fake-server counters.
# ruff: noqa: ASYNC110


async def eventually(
    predicate: Callable[[], bool],
    timeout_seconds: float = 1,
) -> None:
    async with asyncio.timeout(timeout_seconds):
        while not predicate():
            await asyncio.sleep(0)


class SubscriptionTransport:
    closed = False

    def __init__(self) -> None:
        self.subscribers: list[Subscriber] = []
        self.complete_count = 0
        self.gate: asyncio.Event | None = None
        self.complete_before_return = False
        self.subscribe_error: Exception | None = None
        self.unsubscribe_gate: asyncio.Event | None = None
        self.unsubscribe_started: asyncio.Event | None = None

    def on_message(self, _listener: MessageListener) -> Callable[[], None]:
        return lambda: None

    async def subscribe(
        self,
        _query: str,
        _variables: Mapping[str, Any] | None,
        subscriber: Subscriber,
    ) -> Unsubscribe:
        if self.gate is not None:
            await self.gate.wait()
        if self.subscribe_error is not None:
            raise self.subscribe_error
        self.subscribers.append(subscriber)
        if self.complete_before_return:
            subscriber.complete()
        active = True

        async def unsubscribe() -> None:
            nonlocal active
            if active:
                active = False
                self.complete_count += 1
                if self.unsubscribe_started is not None:
                    self.unsubscribe_started.set()
                if self.unsubscribe_gate is not None:
                    await self.unsubscribe_gate.wait()

        return unsubscribe

    async def send(
        self,
        _query: str,
        _variables: Mapping[str, Any] | None = None,
        _timeout: float | None = None,
    ) -> dict[str, Any]:
        return {}

    def operation_timeout(
        self,
        timeout: float | None,
        cushion: float = 0,
    ) -> float:
        return (30_000 if timeout is None else timeout) + cushion

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_no_subscription_before_first_listener() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))

    await asyncio.sleep(0)

    assert transport.subscribers == []
    await page.close()


@pytest.mark.asyncio
async def test_lazy_subscription_sharing_delivery_and_last_off() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    seen: list[str | None] = []

    def first(message: ConsoleMessage) -> None:
        seen.append(message["text"])

    def second(_message: ConsoleMessage) -> None:
        return None

    page.on("console", first)
    page.on("console", second)
    await page._wait_subscription_started("console")

    assert len(transport.subscribers) == 1
    transport.subscribers[0].next({"console": {"text": "hello"}})
    assert seen == ["hello"]
    page.off("console", first)
    await asyncio.sleep(0)
    assert transport.complete_count == 0
    page.off("console", second)
    await eventually(lambda: transport.complete_count == 1)
    await page.close()


@pytest.mark.asyncio
async def test_once_delivers_once_and_unsubscribes() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    seen: list[str | None] = []
    page.once("console", lambda message: seen.append(message["text"]))
    await page._wait_subscription_started("console")

    transport.subscribers[0].next({"console": {"text": "first"}})
    await eventually(lambda: transport.complete_count == 1)
    transport.subscribers[0].next({"console": {"text": "second"}})

    assert seen == ["first"]
    await page.close()


@pytest.mark.asyncio
async def test_distinct_events_use_independent_subscriptions() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    page.on("console", lambda _message: None)
    page.on("request", lambda _message: None)
    page.on("response", lambda _message: None)

    await asyncio.gather(
        page._wait_subscription_started("console"),
        page._wait_subscription_started("request"),
        page._wait_subscription_started("response"),
    )

    assert len(transport.subscribers) == 3
    await page.close()


@pytest.mark.asyncio
async def test_page_close_unsubscribes_active_streams() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    page.on("console", lambda _message: None)
    page.on("request", lambda _message: None)
    await asyncio.gather(
        page._wait_subscription_started("console"),
        page._wait_subscription_started("request"),
    )

    await page.close()

    assert transport.complete_count == 2
    assert transport.closed


@pytest.mark.asyncio
async def test_server_complete_allows_reopen() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    page.on("console", lambda _message: None)
    await page._wait_subscription_started("console")
    transport.subscribers[0].complete()

    page.on("console", lambda _message: None)
    await page._wait_subscription_started("console")
    assert len(transport.subscribers) == 2
    await page.close()


@pytest.mark.asyncio
async def test_complete_before_subscribe_returns_does_not_store_stale_handle() -> None:
    transport = SubscriptionTransport()
    transport.complete_before_return = True
    page = Page(cast(Transport, transport))
    page.on("console", lambda _message: None)
    await page._wait_subscription_started("console")
    transport.complete_before_return = False

    page.on("console", lambda _message: None)
    await page._wait_subscription_started("console")

    assert len(transport.subscribers) == 2
    await page.close()


@pytest.mark.asyncio
async def test_listener_removed_while_connecting_unsubscribes_and_unblocks() -> None:
    transport = SubscriptionTransport()
    transport.gate = asyncio.Event()
    page = Page(cast(Transport, transport))

    def listener(_message: ConsoleMessage) -> None:
        return None

    page.on("console", listener)
    waiter = asyncio.create_task(page._wait_subscription_started("console"))
    page.off("console", listener)
    transport.gate.set()

    await asyncio.wait_for(waiter, 1)
    await eventually(lambda: transport.complete_count == 1)
    assert page.listener_count("console") == 0
    await page.close()


@pytest.mark.asyncio
async def test_listener_readded_during_connect_cleanup_restarts_subscription() -> None:
    transport = SubscriptionTransport()
    transport.gate = asyncio.Event()
    transport.unsubscribe_gate = asyncio.Event()
    transport.unsubscribe_started = asyncio.Event()
    page = Page(cast(Transport, transport))

    def first(_message: ConsoleMessage) -> None:
        return None

    page.on("console", first)
    page.off("console", first)
    transport.gate.set()
    await transport.unsubscribe_started.wait()

    page.on("console", lambda _message: None)
    transport.unsubscribe_gate.set()

    await eventually(lambda: len(transport.subscribers) == 2)
    await page._wait_subscription_started("console")
    assert page.listener_count("console") == 1
    await page.close()


@pytest.mark.asyncio
async def test_listener_readded_before_active_stop_keeps_subscription() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    seen: list[str | None] = []

    def first(_message: ConsoleMessage) -> None:
        return None

    page.on("console", first)
    await page._wait_subscription_started("console")

    page.off("console", first)
    page.on("console", lambda message: seen.append(message["text"]))
    await asyncio.sleep(0)
    transport.subscribers[0].next({"console": {"text": "still active"}})

    assert seen == ["still active"]
    assert transport.complete_count == 0
    assert len(transport.subscribers) == 1
    await page.close()


@pytest.mark.asyncio
async def test_async_event_listener_error_routes_to_error_event() -> None:
    transport = SubscriptionTransport()
    page = Page(cast(Transport, transport))
    errors: list[BaseException] = []
    delivered = asyncio.Event()

    async def listener(_message: ConsoleMessage) -> None:
        delivered.set()
        raise RuntimeError("boom")

    page.on("error", errors.append)
    page.on("console", listener)
    await page._wait_subscription_started("console")
    transport.subscribers[0].next({"console": {"text": "hello"}})
    await delivered.wait()
    await asyncio.sleep(0)
    assert [str(error) for error in errors] == ["boom"]
    await page.close()


@pytest.mark.asyncio
async def test_subscription_start_failure_emits_error_without_storing_handle() -> None:
    transport = SubscriptionTransport()
    transport.subscribe_error = RuntimeError("subscribe failed")
    page = Page(cast(Transport, transport))
    errors: list[BaseException] = []
    page.on("error", errors.append)
    page.on("console", lambda _message: None)

    await page._wait_subscription_started("console")

    assert [str(error) for error in errors] == ["subscribe failed"]
    assert transport.subscribers == []
    assert "console" not in page._unsubscribes
    assert "console" not in page._starting
    await page.close()
