import asyncio
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from browserless_bap.errors import BAPConnectionError, BAPTimeoutError
from browserless_bap.page import Page
from browserless_bap.transport import Subscriber, Transport


class LiveTransport:
    closed = False

    def __init__(self) -> None:
        self.subscriber: Subscriber | None = None
        self.before_reply: Callable[[], None] = lambda: None
        self.calls: list[tuple[str, Any]] = []
        self.starts = 0

    def on_message(self, _listener: Any) -> Callable[[], None]:
        return lambda: None

    def operation_timeout(self, timeout: float | None, cushion: float = 0) -> float:
        resolved = 1000 if timeout is None else timeout
        return resolved + cushion if resolved > 0 else resolved

    async def subscribe(
        self, _query: str, _variables: Any, subscriber: Subscriber
    ) -> Any:
        self.starts += 1
        self.subscriber = subscriber

        async def unsubscribe() -> None:
            pass

        return unsubscribe

    async def send(
        self, query: str, variables: Mapping[str, Any], _timeout: Any
    ) -> Any:
        assert self.subscriber is not None
        self.calls.append((query, variables))
        self.before_reply()
        if "closeLiveURL" in query:
            self.event("closed")
            return {"closeLiveURL": {"liveURLId": "link"}}
        return {"liveURL": {"liveURLId": "link", "liveURL": "https://example.com/live"}}

    def event(self, reason: str, live_url_id: str = "link") -> None:
        assert self.subscriber is not None
        self.subscriber.next(
            {"liveComplete": {"liveURLId": live_url_id, "reason": reason}}
        )

    async def close(self) -> None:
        self.closed = True


async def test_early_completion_and_instructions() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    transport.before_reply = lambda: transport.event("userDone")
    seen: list[object] = []
    page.on("liveComplete", seen.append)
    await page.live_url(instructions="Sign in")
    assert transport.calls[0][1]["instructions"] == "Sign in"
    assert (await page.wait_for_live_complete())["reason"] == "userDone"
    assert len(seen) == 1
    assert transport.starts == 1
    await page.close()


async def test_live_url_passes_rich_instructions_unchanged() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url(
        instructions={
            "layout": "panel",
            "format": "markdown",
            "title": "Login",
            "summary": "**Sign in**",
            "steps": ["Enter code"],
            "currentStep": 1,
        },
        done_label="Go",
    )
    query, variables = transport.calls[0]
    assert "$instructions: StringOrInstructions" in query
    assert variables == {
        "instructions": {
            "layout": "panel",
            "format": "markdown",
            "title": "Login",
            "summary": "**Sign in**",
            "steps": ["Enter code"],
            "currentStep": 1,
        },
        "doneLabel": "Go",
    }
    await page.live_url(instructions={"layout": "sidebar"})  # type: ignore[arg-type]
    await page.close()


async def test_remint_retains_only_the_new_completion() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url()
    old = asyncio.create_task(page.wait_for_live_complete())
    await asyncio.sleep(0)

    def replace() -> None:
        transport.event("closed")
        transport.event("timeout")

    transport.before_reply = replace
    await page.live_url()
    assert (await old)["reason"] == "closed"
    assert (await page.wait_for_live_complete())["reason"] == "timeout"
    await page.close()


async def test_wait_before_mint_and_independent_timeout() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    waiting = asyncio.create_task(page.wait_for_live_complete(timeout=0))
    await asyncio.sleep(0)
    await page.live_url()
    with pytest.raises(BAPTimeoutError):
        await page.wait_for_live_complete(timeout=5)
    transport.event("userFailed")
    assert (await waiting)["reason"] == "userFailed"
    assert (await page.wait_for_live_complete())["reason"] == "userFailed"
    await page.close()


@pytest.mark.parametrize("disconnect", [True, False])
async def test_wait_rejects_on_disconnect_or_close(disconnect: bool) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url()
    waiting = asyncio.create_task(page.wait_for_live_complete(timeout=0))
    await asyncio.sleep(0)
    if disconnect:
        assert transport.subscriber is not None
        transport.subscriber.error(BAPConnectionError("disconnected"))
    else:
        await page.close()
    with pytest.raises(BAPConnectionError):
        await waiting
    await page.close()


async def test_close_live_url_returns_the_id() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url()
    assert await page.close_live_url("link") == {"liveURLId": "link"}
    assert (await page.wait_for_live_complete())["reason"] == "closed"
    await page.close()


async def test_cancelled_wait_does_not_cancel_retained_completion() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url()
    waiting = asyncio.create_task(page.wait_for_live_complete(timeout=0))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    transport.event("userDone")
    assert (await page.wait_for_live_complete())["reason"] == "userDone"
    await page.close()


async def test_pending_listener_removal_does_not_stop_handoff_subscription() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))

    def listener(_event: object) -> None:
        pass

    page.on("liveComplete", listener)
    await page._wait_subscription_started("liveComplete")
    page.off("liveComplete", listener)
    await page.live_url()
    await asyncio.sleep(0)
    assert "liveComplete" in page._unsubscribes
    transport.event("closed")
    assert (await page.wait_for_live_complete())["reason"] == "closed"
    await page.close()


@pytest.mark.parametrize("end", ["event", "close"])
async def test_waits_survive_multiple_remints(end: str) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    waits = []
    for _ in range(3):
        await page.live_url()
        waits.append(asyncio.create_task(page.wait_for_live_complete(timeout=0)))
        await asyncio.sleep(0)
    if end == "close":
        await page.close()
        results = await asyncio.gather(*waits, return_exceptions=True)
        assert all(isinstance(result, BAPConnectionError) for result in results)
    else:
        for reason in ["closed", "userDone", "timeout"]:
            transport.event(reason)
        assert [event["reason"] for event in await asyncio.gather(*waits)] == [
            "closed",
            "userDone",
            "timeout",
        ]
        await page.close()


async def test_mint_timeout_keeps_its_original_error() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    error = BAPTimeoutError("liveURL", 25)

    def fail() -> None:
        raise error

    transport.before_reply = fail
    waiting = asyncio.create_task(page.wait_for_live_complete(timeout=0))
    await asyncio.sleep(0)
    with pytest.raises(BAPTimeoutError) as mint_error:
        await page.live_url()
    with pytest.raises(BAPTimeoutError) as wait_error:
        await waiting
    assert mint_error.value is error
    assert wait_error.value is error
    await page.close()


@pytest.mark.parametrize("wait_before_failure", [False, True])
async def test_stream_failure_retained_until_remint(wait_before_failure: bool) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    await page.live_url()
    waiting = None
    if wait_before_failure:
        waiting = asyncio.create_task(page.wait_for_live_complete(timeout=0))
        await asyncio.sleep(0)
    assert transport.subscriber is not None
    error = BAPConnectionError("disconnected")
    transport.subscriber.error(error)
    if waiting is not None:
        with pytest.raises(BAPConnectionError) as wait_error:
            await waiting
        assert wait_error.value is error
    for _ in range(2):
        with pytest.raises(BAPConnectionError) as wait_error:
            await page.wait_for_live_complete(timeout=5)
        assert wait_error.value is error
    await page.live_url()
    transport.event("userDone")
    assert (await page.wait_for_live_complete())["reason"] == "userDone"
    await page.close()


async def test_failed_handoff_retained_during_mint_then_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    entered = asyncio.Event()
    release = asyncio.Event()
    error = BAPConnectionError("disconnected")
    original_send = transport.send

    async def send(*_args: Any) -> Any:
        entered.set()
        await release.wait()
        raise error

    monkeypatch.setattr(transport, "send", send)
    mint = asyncio.create_task(page.live_url())
    await entered.wait()
    assert transport.subscriber is not None
    transport.subscriber.error(error)
    try:
        with pytest.raises(BAPConnectionError) as wait_error:
            await page.wait_for_live_complete(timeout=5)
        assert wait_error.value is error
    finally:
        release.set()
        with pytest.raises(BAPConnectionError):
            await mint

    monkeypatch.setattr(transport, "send", original_send)
    retry = asyncio.create_task(page.wait_for_live_complete(timeout=0))
    await asyncio.sleep(0)
    await page.live_url()
    transport.event("userDone")
    assert (await retry)["reason"] == "userDone"
    await page.close()


@pytest.mark.parametrize("kind", ["none", "once", "off"])
async def test_idle_subscription_stops_and_retains_completion(kind: str) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))

    def listener(_event: object) -> None:
        pass

    if kind == "once":
        page.once("liveComplete", listener)
    if kind == "off":
        page.on("liveComplete", listener)
    await page.live_url()
    transport.event("userDone")
    await asyncio.sleep(0)
    if kind == "off":
        assert "liveComplete" in page._unsubscribes
        page.off("liveComplete", listener)
        await asyncio.sleep(0)
    assert "liveComplete" not in page._unsubscribes
    assert (await page.wait_for_live_complete())["reason"] == "userDone"
    assert transport.starts == 1
    await page.live_url()
    assert transport.starts == 2
    transport.event("closed")
    assert (await page.wait_for_live_complete())["reason"] == "closed"
    await page.close()


@pytest.mark.parametrize("matching", [False, True])
async def test_early_completion_matches_minted_id(matching: bool) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))

    def before_reply() -> None:
        transport.event("userDone", "unrelated")
        if matching:
            transport.event("closed")

    transport.before_reply = before_reply
    await page.live_url()
    if not matching:
        with pytest.raises(BAPTimeoutError):
            await page.wait_for_live_complete(timeout=5)
        transport.event("closed")
    assert await page.wait_for_live_complete() == {
        "liveURLId": "link",
        "reason": "closed",
    }
    await page.close()


async def test_last_premint_wait_releases_subscription() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    with pytest.raises(BAPTimeoutError):
        await page.wait_for_live_complete(timeout=5)
    await asyncio.sleep(0)
    assert "liveComplete" not in page._unsubscribes
    await page.live_url()
    assert transport.starts == 2
    transport.event("userDone")
    assert (await page.wait_for_live_complete())["reason"] == "userDone"
    await page.close()


async def test_premint_timeout_preserves_other_waiter() -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    waiting = asyncio.create_task(page.wait_for_live_complete())
    await asyncio.sleep(0)
    with pytest.raises(BAPTimeoutError):
        await page.wait_for_live_complete(timeout=5)
    assert "liveComplete" in page._unsubscribes
    await page.live_url()
    transport.event("userDone")
    assert (await waiting)["reason"] == "userDone"
    await page.close()


async def test_mint_cancellation_does_not_cancel_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    entered = asyncio.Event()

    async def send(*_args: Any) -> Any:
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(transport, "send", send)
    waiting = asyncio.create_task(page.wait_for_live_complete())
    await asyncio.sleep(0)
    mint = asyncio.create_task(page.live_url())
    await entered.wait()
    mint.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mint
    with pytest.raises(BAPConnectionError, match="cancelled"):
        await waiting
    assert not waiting.cancelled()
    await page.close()


async def test_default_wait_has_no_operation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = LiveTransport()
    page = Page(cast(Transport, transport))
    monkeypatch.setattr(transport, "operation_timeout", lambda _timeout, _cushion=0: 1)
    await page.live_url()
    waiting = asyncio.create_task(page.wait_for_live_complete())
    await asyncio.sleep(0.01)
    transport.event("userDone")
    assert (await waiting)["reason"] == "userDone"
    await page.close()
