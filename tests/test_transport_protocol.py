import asyncio
import gc
import json
import logging
from typing import cast

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from browserless_bap.errors import BAPConnectionError, BAPTimeoutError, BrowserQLError
from browserless_bap.transport import (
    Subscriber,
    Transport,
    TransportFactory,
    TransportHandlers,
    _Operation,
    _RedactSecrets,
    _safe_error_message,
    _WebSocketConnection,
)


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

    def receive(self, frame: dict[str, object] | str) -> None:
        assert self.handlers is not None
        message = frame if isinstance(frame, str) else json.dumps(frame)
        self.handlers.on_message(message)

    def drop(self) -> None:
        assert self.handlers is not None
        self.handlers.on_close(None)

    def fail(self, error: object) -> None:
        assert self.handlers is not None
        self.handlers.on_error(error)


class SlowConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.in_send = False
        self.overlapped = False
        self.two_operations_sent = asyncio.Event()

    async def send(self, message: str) -> None:
        if self.in_send:
            self.overlapped = True
        self.in_send = True
        await asyncio.sleep(0)
        await super().send(message)
        self.in_send = False
        if len(self.sent) == 3:
            self.two_operations_sent.set()


class CancellingSendConnection(FakeConnection):
    cancel_sends = False

    async def send(self, message: str) -> None:
        if self.cancel_sends:
            raise asyncio.CancelledError
        await super().send(message)


class AbnormalCloseSocket:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.sent: list[str] = []
        self.closed = False
        self._raised = False

    def __aiter__(self) -> "AbnormalCloseSocket":
        return self

    async def __anext__(self) -> str:
        if self._raised:
            raise StopAsyncIteration
        await self.release.wait()
        self._raised = True
        raise ConnectionClosedError(
            Close(4403, "quota exhausted at ?token=super-secret"),
            None,
        )

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True
        self.release.set()


async def connected_transport() -> tuple[Transport, FakeConnection]:
    connection = FakeConnection()
    transport = Transport("ws://unused", transport_factory=lambda _url: connection)
    await transport.connect()
    return transport, connection


@pytest.mark.parametrize("connect_timeout", [None, 20])
async def test_connect_timeout_is_typed_and_terminal(
    connect_timeout: float | None,
) -> None:
    async def factory(_url: str | None) -> FakeConnection:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    transport = Transport(
        "ws://unused",
        default_timeout=40,
        transport_factory=cast(TransportFactory, factory),
        connect_timeout=connect_timeout,
    )
    async with asyncio.timeout(1):
        with pytest.raises(BAPTimeoutError) as caught:
            await transport.connect()
        assert caught.value.operation == "connect"
        assert caught.value.timeout_ms == (40 if connect_timeout is None else 20)
        assert caught.value.__context__ is None
        assert transport.closed
        with pytest.raises((BAPConnectionError, BAPTimeoutError)):
            await transport.send("query { x }")
    await transport.close()


@pytest.mark.parametrize("connect_timeout", [0, -1])
async def test_connect_timeout_disabled(connect_timeout: float) -> None:
    connection = FakeConnection()

    async def factory(_url: str | None) -> FakeConnection:
        await asyncio.sleep(0.05)
        return connection

    transport = Transport(
        "ws://unused",
        default_timeout=10,
        transport_factory=cast(TransportFactory, factory),
        connect_timeout=connect_timeout,
    )
    await transport.connect()
    assert not transport.closed
    await transport.close()


async def test_failed_connection_init_closes_connection() -> None:
    class BrokenConnection(FakeConnection):
        async def send(self, message: str) -> None:
            raise OSError("socket gone ?token=SECRET")

    connection = BrokenConnection()
    transport = Transport("ws://unused", transport_factory=lambda _url: connection)
    with pytest.raises(BAPConnectionError) as caught:
        await transport.connect()
    assert connection.closed
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SECRET" not in str(caught.value)
    await transport.close()


async def test_connect_timeout_survives_stalled_cleanup() -> None:
    class StalledConnection(FakeConnection):
        async def send(self, message: str) -> None:
            await asyncio.Event().wait()

        async def close(self) -> None:
            await asyncio.Event().wait()

    transport = Transport(
        "ws://unused",
        transport_factory=lambda _url: StalledConnection(),
        connect_timeout=20,
    )
    async with asyncio.timeout(6):
        with pytest.raises(BAPTimeoutError) as caught:
            await transport.connect()
    assert caught.value.operation == "connect"
    assert caught.value.timeout_ms == 20
    assert caught.value.__context__ is None
    assert transport.closed
    await transport.close()


@pytest.mark.parametrize("stage", ["factory", "init"])
async def test_connect_rejects_suppressed_deadline_cancellation(stage: str) -> None:
    async def stall() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    class LateConnection(FakeConnection):
        async def send(self, message: str) -> None:
            if stage == "init":
                await stall()
            await super().send(message)

    connection = LateConnection()

    async def factory(_url: str | None) -> FakeConnection:
        if stage == "factory":
            await stall()
        return connection

    transport = Transport(
        "ws://unused",
        transport_factory=cast(TransportFactory, factory),
        connect_timeout=20,
    )
    async with asyncio.timeout(1):
        with pytest.raises(BAPTimeoutError) as caught:
            await transport.connect()
    assert caught.value.operation == "connect"
    assert caught.value.timeout_ms == 20
    assert connection.closed
    assert transport.closed
    await transport.close()


async def test_cancelled_connect_waiter_does_not_poison_others() -> None:
    sent = asyncio.Event()

    class SignallingConnection(FakeConnection):
        async def send(self, message: str) -> None:
            await super().send(message)
            if json.loads(message)["type"] == "subscribe":
                sent.set()

    connection = SignallingConnection()
    gate = asyncio.Event()
    started = asyncio.Event()

    async def factory(_url: str | None) -> FakeConnection:
        started.set()
        await gate.wait()
        return connection

    transport = Transport(
        "ws://unused", transport_factory=cast(TransportFactory, factory)
    )
    one: asyncio.Task[object] = asyncio.create_task(transport.send("query { x }"))
    two: asyncio.Task[object] = asyncio.create_task(transport.send("query { y }"))
    await started.wait()
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    gate.set()
    async with asyncio.timeout(1):
        await sent.wait()
        connection.receive({"id": "1", "type": "next", "payload": {"data": {"y": 2}}})
        connection.receive({"id": "1", "type": "complete"})
        assert await two == {"y": 2}
        sent.clear()
        three: asyncio.Task[object] = asyncio.create_task(transport.send("query { z }"))
        await sent.wait()
        connection.receive({"id": "2", "type": "complete"})
        assert await three == {}
    await transport.close()


async def test_abandoned_connect_failure_has_no_unretrieved_exception() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def factory(_url: str | None) -> FakeConnection:
        started.set()
        await release.wait()
        finished.set()
        raise ConnectionError("factory failed")

    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        transport = Transport(
            "ws://unused", transport_factory=cast(TransportFactory, factory)
        )
        waiter: asyncio.Task[object] = asyncio.create_task(
            transport.send("query { x }")
        )
        await started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        del waiter
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        await transport.close()
        del transport
        gc.collect()
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


async def test_complete_during_timeout_still_raises_timeout() -> None:
    class EchoComplete(FakeConnection):
        async def send(self, message: str) -> None:
            await super().send(message)
            frame = json.loads(message)
            if frame["type"] == "complete":
                self.receive(frame)

    connection = EchoComplete()
    transport = Transport("ws://unused", transport_factory=lambda _url: connection)
    with pytest.raises(BAPTimeoutError):
        await transport.send("query { x }", timeout=10)
    assert connection.sent[-1] == {"id": "1", "type": "complete"}
    await transport.close()


async def test_subscription_error_completes_stream_and_tells_server() -> None:
    transport, connection = await connected_transport()
    errors: list[Exception] = []
    values: list[object] = []
    await transport.subscribe(
        "subscription { x }",
        None,
        Subscriber(
            next=values.append,
            error=errors.append,
            complete=lambda: None,
        ),
    )
    connection.receive(
        {"id": "1", "type": "next", "payload": {"errors": [{"message": "bad one"}]}}
    )
    await asyncio.sleep(0)
    connection.receive({"id": "1", "type": "next", "payload": {"data": {"x": 1}}})
    assert len(errors) == 1
    assert isinstance(errors[0], BrowserQLError)
    assert str(errors[0]) == "bad one"
    assert not values
    assert [f for f in connection.sent if f["type"] == "complete"] == [
        {"id": "1", "type": "complete"}
    ]
    await transport.close()


@pytest.mark.parametrize("entry", ["boom", 42, None])
@pytest.mark.parametrize("frame_type", ["error", "next"])
async def test_malformed_error_payload_fails_only_that_operation(
    entry: object,
    frame_type: str,
) -> None:
    transport, connection = await connected_transport()
    task: asyncio.Task[object] = asyncio.create_task(transport.send("query { x }"))
    await asyncio.sleep(0)
    payload = [entry] if frame_type == "error" else {"errors": [entry]}
    connection.receive({"id": "1", "type": frame_type, "payload": payload})
    with pytest.raises(BrowserQLError, match=str(entry)):
        await task
    assert not transport.closed
    following: asyncio.Task[object] = asyncio.create_task(transport.send("query { y }"))
    await asyncio.sleep(0)
    connection.receive({"id": "2", "type": "next", "payload": {"data": {"y": 7}}})
    connection.receive({"id": "2", "type": "complete"})
    assert await following == {"y": 7}
    await transport.close()


async def test_empty_errors_list_is_success() -> None:
    transport, connection = await connected_transport()
    task: asyncio.Task[object] = asyncio.create_task(transport.send("query { x }"))
    await asyncio.sleep(0)
    connection.receive(
        {"id": "1", "type": "next", "payload": {"data": {"x": 1}, "errors": []}}
    )
    connection.receive({"id": "1", "type": "complete"})
    assert await task == {"x": 1}
    await transport.close()


@pytest.mark.parametrize("closed", [False, True])
async def test_unsubscribe_never_raises(closed: bool) -> None:
    class BrokenSend(FakeConnection):
        broken = False

        async def send(self, message: str) -> None:
            if self.broken:
                raise OSError("socket gone")
            await super().send(message)

    connection = BrokenSend()
    transport = Transport("ws://unused", transport_factory=lambda _url: connection)
    unsubscribe = await transport.subscribe(
        "subscription { x }",
        None,
        Subscriber(
            next=lambda _value: None,
            error=lambda _error: None,
            complete=lambda: None,
        ),
    )
    if closed:
        await transport.close()
    connection.broken = True
    count = len(connection.sent)
    await unsubscribe()
    await unsubscribe()
    assert len(connection.sent) == count
    await transport.close()


@pytest.mark.parametrize("site", ["factory", "dial", "send", "factory_timeout"])
async def test_connection_errors_have_no_context(site: str) -> None:
    class BrokenSend(FakeConnection):
        async def send(self, message: str) -> None:
            if json.loads(message)["type"] == "subscribe":
                raise OSError("send failed ?token=SECRET")
            await super().send(message)

    def factory(_url: str | None) -> FakeConnection:
        if site == "factory":
            raise RuntimeError("dial failed wss://h/bql?token=SECRET")
        if site == "factory_timeout":
            raise TimeoutError("dial failed ?token=SECRET")
        return BrokenSend()

    transport = Transport(
        "https://example.invalid/bql?token=SECRET",
        transport_factory=None if site == "dial" else cast(TransportFactory, factory),
    )
    with pytest.raises(BAPConnectionError) as caught:
        await transport.send("query { x }")
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SECRET" not in str(caught.value)
    await transport.close()


def test_log_filter_survives_bad_records() -> None:
    for message, args, expected in [
        ("", (), ""),
        ("GET /bql?token=abc", (), "GET /bql?token=<redacted>"),
    ]:
        record = logging.LogRecord("test", logging.DEBUG, "", 0, message, args, None)
        assert _RedactSecrets().filter(record)
        assert record.msg == expected


def test_bad_log_format_does_not_leak_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.Logger("redaction-test", logging.DEBUG)
    logger.addFilter(_RedactSecrets())
    logger.addHandler(logging.StreamHandler())
    logger.debug("GET /bql?token=SECRET %d", "x")

    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert "Logging error" not in captured.err


@pytest.mark.asyncio
async def test_connect_is_memoized_and_sends_are_serialized() -> None:
    connection = SlowConnection()
    factory_calls = 0

    def factory(_url: str | None) -> SlowConnection:
        nonlocal factory_calls
        factory_calls += 1
        return connection

    transport = Transport(
        "ws://unused",
        transport_factory=cast(TransportFactory, factory),
    )
    first = transport.connect()
    second = transport.connect()
    assert first is second
    await asyncio.gather(first, second)

    one: asyncio.Task[dict[str, int]] = asyncio.create_task(
        transport.send("query { one }")
    )
    two: asyncio.Task[dict[str, int]] = asyncio.create_task(
        transport.send("query { two }")
    )
    await connection.two_operations_sent.wait()
    connection.receive(
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"one": 1}},
        }
    )
    connection.receive(
        {
            "id": "2",
            "type": "next",
            "payload": {"data": {"two": 2}},
        }
    )
    assert not one.done()
    assert not two.done()
    connection.receive({"id": "1", "type": "complete"})
    connection.receive({"id": "2", "type": "complete"})

    assert await one == {"one": 1}
    assert await two == {"two": 2}
    assert factory_calls == 1
    assert not connection.overlapped
    await transport.close()


@pytest.mark.asyncio
async def test_connect_preserves_factory_cancellation() -> None:
    started = asyncio.Event()

    async def factory(_url: str | None) -> FakeConnection:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    transport = Transport(
        "ws://unused",
        transport_factory=cast(TransportFactory, factory),
    )
    task = cast(asyncio.Task[None], transport.connect())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await transport.close()


@pytest.mark.asyncio
async def test_close_closes_connection_returned_during_cancel_race() -> None:
    connection = FakeConnection()
    started = asyncio.Event()

    async def factory(_url: str | None) -> FakeConnection:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return connection
        raise AssertionError("unreachable")

    transport = Transport(
        "ws://unused",
        transport_factory=cast(TransportFactory, factory),
    )
    transport.connect()
    await started.wait()

    await transport.close()

    assert connection.closed
    assert transport.closed


@pytest.mark.asyncio
async def test_send_preserves_connection_cancellation() -> None:
    connection = CancellingSendConnection()
    transport = Transport(
        "ws://unused",
        transport_factory=lambda _url: connection,
    )
    await transport.connect()
    connection.cancel_sends = True

    with pytest.raises(asyncio.CancelledError):
        await transport.send("query { ping }")

    connection.cancel_sends = False
    await transport.close()


@pytest.mark.asyncio
async def test_injection_next_complete_ack_and_raw_broadcast() -> None:
    transport, connection = await connected_transport()
    assert connection.sent == [{"type": "connection_init"}]
    seen: list[str] = []
    transport.on_message(seen.append)

    task: asyncio.Task[dict[str, str]] = asyncio.create_task(
        transport.send("query { ping }")
    )
    await asyncio.sleep(0)
    assert connection.sent[1] == {
        "id": "1",
        "type": "subscribe",
        "payload": {"query": "query { ping }"},
    }
    connection.receive({"type": "connection_ack"})
    connection.receive({"push": 1})
    connection.receive(
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"ping": "pong"}},
        }
    )
    assert not task.done()
    connection.receive({"id": "1", "type": "complete"})

    assert await task == {"ping": "pong"}
    assert len(seen) == 3
    await transport.close()


@pytest.mark.asyncio
async def test_send_waits_for_complete_and_drop_after_next_rejects() -> None:
    transport, connection = await connected_transport()
    task: asyncio.Task[dict[str, str]] = asyncio.create_task(
        transport.send("query { ping }")
    )
    await asyncio.sleep(0)
    connection.receive(
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"ping": "pong"}},
        }
    )
    assert not task.done()

    connection.drop()

    with pytest.raises(BAPConnectionError, match="closed unexpectedly"):
        await task


@pytest.mark.asyncio
async def test_ping_is_answered_and_pong_is_consumed() -> None:
    transport, connection = await connected_transport()
    seen: list[str] = []
    transport.on_message(seen.append)

    connection.receive({"type": "ping", "payload": {"nonce": 1}})
    await asyncio.sleep(0)
    connection.receive({"type": "pong", "payload": {"nonce": 1}})

    assert connection.sent[-1] == {
        "type": "pong",
        "payload": {"nonce": 1},
    }
    assert seen == []
    await transport.close()


@pytest.mark.asyncio
async def test_cancellation_sends_complete_and_stops_operation() -> None:
    transport, connection = await connected_transport()
    task: asyncio.Task[dict[str, bool]] = asyncio.create_task(
        transport.send("mutation { slow }", timeout=0)
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert connection.sent[-1] == {"id": "1", "type": "complete"}
    connection.receive(
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"slow": True}},
        }
    )
    await transport.close()


@pytest.mark.asyncio
async def test_timeout_sends_complete_before_raising() -> None:
    transport, connection = await connected_transport()
    with pytest.raises(BAPTimeoutError):
        await transport.send("mutation { slow }", timeout=1)

    assert connection.sent[-1] == {"id": "1", "type": "complete"}
    await transport.close()


@pytest.mark.asyncio
async def test_drop_marks_closed_and_fails_subscriber() -> None:
    transport, connection = await connected_transport()
    errors: list[Exception] = []
    await transport.subscribe(
        "subscription { console { text } }",
        None,
        Subscriber(
            next=lambda _value: None,
            error=errors.append,
            complete=lambda: None,
        ),
    )
    connection.drop()

    assert transport.closed
    assert len(errors) == 1
    assert isinstance(errors[0], BAPConnectionError)
    await transport.close()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([{"message": "top-level failure"}], "top-level failure"),
        ({"message": "malformed"}, "Unknown BrowserQL error"),
    ],
)
@pytest.mark.asyncio
async def test_top_level_error_frame_fails_operation(
    payload: object,
    message: str,
) -> None:
    transport, connection = await connected_transport()
    task: asyncio.Task[dict[str, object]] = asyncio.create_task(
        transport.send("query { ping }")
    )
    await asyncio.sleep(0)

    connection.receive({"id": "1", "type": "error", "payload": payload})

    with pytest.raises(BrowserQLError, match=message):
        await task
    await transport.close()


@pytest.mark.asyncio
async def test_connection_error_fails_operations_and_redacts_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, connection = await connected_transport()

    def fail_callback(_error: Exception) -> None:
        raise RuntimeError("subscriber callback failed")

    await transport.subscribe(
        "subscription { console { text } }",
        None,
        Subscriber(
            next=lambda _value: None,
            error=fail_callback,
            complete=lambda: None,
        ),
    )
    task: asyncio.Task[dict[str, object]] = asyncio.create_task(
        transport.send("query { ping }")
    )
    await asyncio.sleep(0)
    caplog.set_level("ERROR", logger="browserless_bap")

    connection.fail(
        RuntimeError(
            "socket failed at ws://example.test/chromium/bql?token=super-secret"
        )
    )

    with pytest.raises(BAPConnectionError) as raised:
        await task
    assert transport.closed
    assert "super-secret" not in str(raised.value)
    assert "token=<redacted>" in str(raised.value)
    assert "Unhandled exception in bap transport callback" in caplog.text
    await transport.close()


@pytest.mark.parametrize(
    ("url", "redacted"),
    [
        (
            "wss://user:websocket-secret@example.test/chromium/bql",
            "wss://<redacted>@example.test/chromium/bql",
        ),
        (
            "http://username:proxy-secret@proxy.test:12321",
            "http://<redacted>@proxy.test:12321",
        ),
    ],
)
def test_safe_error_message_redacts_url_userinfo(
    url: str,
    redacted: str,
) -> None:
    message = _safe_error_message(RuntimeError(f"connection failed at {url}"))

    assert redacted in message
    assert "websocket-secret" not in message
    assert "proxy-secret" not in message
    assert "username" not in message


@pytest.mark.asyncio
async def test_abnormal_websocket_close_preserves_reason_and_redacts_token() -> None:
    socket = AbnormalCloseSocket()
    transport = Transport(
        "ws://unused",
        transport_factory=lambda _url: _WebSocketConnection(
            cast(ClientConnection, socket)
        ),
    )
    await transport.connect()
    task: asyncio.Task[dict[str, object]] = asyncio.create_task(
        transport.send("query { ping }")
    )
    await asyncio.sleep(0)

    socket.release.set()

    with pytest.raises(BAPConnectionError) as raised:
        await task
    message = str(raised.value)
    assert transport.closed
    assert "4403" in message
    assert "quota exhausted" in message
    assert "super-secret" not in message
    assert "token=<redacted>" in message
    await transport.close()


@pytest.mark.asyncio
async def test_subscriber_unsubscribe_sends_one_complete_and_is_idempotent() -> None:
    transport, connection = await connected_transport()
    unsubscribe = await transport.subscribe(
        "subscription { console { text } }",
        None,
        Subscriber(
            next=lambda _value: None,
            error=lambda _error: None,
            complete=lambda: None,
        ),
    )

    await asyncio.gather(unsubscribe(), unsubscribe())

    completes = [frame for frame in connection.sent if frame["type"] == "complete"]
    assert completes == [{"id": "1", "type": "complete"}]
    await transport.close()


def test_operation_requires_exactly_one_result_consumer() -> None:
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        subscriber = Subscriber(
            next=lambda _value: None,
            error=lambda _error: None,
            complete=lambda: None,
        )
        with pytest.raises(ValueError, match="exactly one"):
            _Operation()
        with pytest.raises(ValueError, match="exactly one"):
            _Operation(future=future, subscriber=subscriber)
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_non_json_frame_is_broadcast_with_debug_signal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, connection = await connected_transport()
    seen: list[str] = []
    transport.on_message(seen.append)
    caplog.set_level("DEBUG", logger="browserless_bap")

    connection.receive("not-json token=do-not-log")

    assert seen == ["not-json token=do-not-log"]
    assert "Received non-JSON BrowserQL frame" in caplog.text
    assert "do-not-log" not in caplog.text
    await transport.close()


@pytest.mark.asyncio
async def test_async_transport_callback_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, connection = await connected_transport()

    async def fail(_value: object) -> None:
        raise RuntimeError("async callback failed")

    await transport.subscribe(
        "subscription { console { text } }",
        None,
        Subscriber(
            next=fail,
            error=lambda _error: None,
            complete=lambda: None,
        ),
    )
    caplog.set_level("ERROR", logger="browserless_bap")

    connection.receive(
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"console": {"text": "hello"}}},
        }
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert "Unhandled exception in bap transport callback" in caplog.text
    assert "async callback failed" in caplog.text
    await transport.close()
