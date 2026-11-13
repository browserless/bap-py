"""GraphQL-over-WebSocket transport for Browser Automation Protocol."""

# Remote-operation timeouts are intentional public API parameters.
# ruff: noqa: ASYNC109

from __future__ import annotations

import asyncio
import builtins
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, TypeVar, cast

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK
from websockets.typing import Subprotocol

from .errors import BAPConnectionError, BAPTimeoutError, BrowserQLError

try:
    from ._version import __version__
except ImportError:  # pragma: no cover - only possible in a broken source tree
    __version__ = "0.0.0"

SUBPROTOCOL = "graphql-transport-ws"
OPERATION_TIMEOUT_CUSHION_MS = 5_000
T = TypeVar("T")
MaybeAwaitable: TypeAlias = Awaitable[None] | None
Unsubscribe: TypeAlias = Callable[[], Awaitable[None]]
MessageListener: TypeAlias = Callable[[str], object]
logger = logging.getLogger("browserless_bap")


class _RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return False
        record.msg = re.sub(
            r"(Authorization: )[^\r\n]+",
            r"\1<redacted>",
            _redact(message),
            flags=re.IGNORECASE,
        )
        record.args = ()
        return True


_WEBSOCKETS_LOGGER = logging.getLogger("browserless_bap.websockets")
_WEBSOCKETS_LOGGER.addFilter(_RedactSecrets())


@dataclass(frozen=True, slots=True)
class TransportHandlers:
    """Callbacks a pluggable connection must bind before any frame is sent."""

    on_message: Callable[[str], None]
    on_close: Callable[[object | None], None]
    on_error: Callable[[object], None]


class ConnectionTransport(Protocol):
    """The framing-free connection seam used by :class:`Transport`."""

    def bind(self, handlers: TransportHandlers) -> None: ...

    def send(self, message: str) -> MaybeAwaitable: ...

    def close(self) -> MaybeAwaitable: ...


class TransportFactory(Protocol):
    """Create one fresh connection for each BAP page."""

    def __call__(
        self, url: str | None
    ) -> ConnectionTransport | Awaitable[ConnectionTransport]: ...


@dataclass(slots=True)
class Subscriber:
    """Callbacks for one streaming GraphQL operation."""

    next: Callable[[Mapping[str, Any]], object]
    error: Callable[[Exception], object]
    complete: Callable[[], object]


@dataclass(slots=True)
class _Operation:
    future: asyncio.Future[Any] | None = None
    subscriber: Subscriber | None = None
    result: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.future is None) == (self.subscriber is None):
            raise ValueError("Operation requires exactly one result consumer")


class _WebSocketConnection:
    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._handlers: TransportHandlers | None = None
        self._receive_task: asyncio.Task[None] | None = None

    def bind(self, handlers: TransportHandlers) -> None:
        if self._handlers is not None:
            raise RuntimeError("Connection transport is already bound")
        self._handlers = handlers
        self._receive_task = asyncio.create_task(self._receive())

    async def send(self, message: str) -> None:
        await self._socket.send(message)

    async def close(self) -> None:
        await self._socket.close()
        task = self._receive_task
        if task is not None and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)

    async def _receive(self) -> None:
        assert self._handlers is not None
        try:
            async for message in self._socket:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                self._handlers.on_message(message)
        except ConnectionClosedOK:
            pass
        except ConnectionClosed as exc:
            self._handlers.on_error(exc)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._handlers.on_error(exc)
        finally:
            self._handlers.on_close(None)


class Transport:
    """Multiplex BAP operations over one ``graphql-transport-ws`` socket."""

    def __init__(
        self,
        url: str | None,
        default_timeout: float = 30_000,
        transport_factory: TransportFactory | None = None,
        *,
        connect_timeout: float | None = None,
    ) -> None:
        self._url = url
        self._default_timeout = default_timeout
        self._connect_timeout = connect_timeout
        self._transport_factory = transport_factory
        self._connection: ConnectionTransport | None = None
        self._ready: asyncio.Task[None] | None = None
        self._operations: dict[str, _Operation] = {}
        self._next_id = 0
        self._closed = False
        self._closing = False
        self._connected = False
        self._send_lock = asyncio.Lock()
        self._message_listeners: dict[MessageListener, None] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def closed(self) -> bool:
        return self._closed

    def connect(self) -> Awaitable[None]:
        """Return the one shared in-flight connection task."""

        if self._ready is None:
            self._ready = asyncio.create_task(self._connect())
            self._ready.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        return self._ready

    async def _connect(self) -> None:
        if self._closed:
            raise BAPConnectionError("Transport is closed")
        deadline = self.operation_timeout(self._connect_timeout)
        connection: ConnectionTransport | None = None
        cm = asyncio.timeout(deadline / 1000 if deadline > 0 else None)
        try:
            async with cm:
                if self._transport_factory is None:
                    connection = await self._dial()
                else:
                    created = self._transport_factory(self._url)
                    connection = (
                        await created if inspect.isawaitable(created) else created
                    )
                connection.bind(
                    TransportHandlers(
                        on_message=self._on_frame,
                        on_close=self._on_close,
                        on_error=self._on_error,
                    )
                )
                self._connection = connection
                await self._send_frame({"type": "connection_init"})
                if cm.expired():
                    raise builtins.TimeoutError
                self._connected = True
            return
        except builtins.TimeoutError as exc:
            error: Exception = (
                BAPTimeoutError("connect", deadline)
                if cm.expired()
                else BAPConnectionError(
                    f"WebSocket connection failed: {_safe_error_message(exc)}"
                )
            )
        except BAPConnectionError as exc:
            error = BAPConnectionError(_safe_error_message(exc))
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            error = BAPConnectionError(
                f"WebSocket connection failed: {_safe_error_message(exc)}"
            )
        finally:
            if not self._connected:
                self._closed = True
                if connection is not None:
                    with suppress(Exception):
                        async with asyncio.timeout(5):
                            await _maybe_await(connection.close())
                self._connection = None
        raise error

    async def _dial(self) -> ConnectionTransport:
        if self._url is None:
            raise BAPConnectionError(
                "A browser_ws_endpoint is required when no transport is provided"
            )
        try:
            socket = await connect(
                self._url,
                subprotocols=[Subprotocol(SUBPROTOCOL)],
                additional_headers={"User-Agent": f"browserless-bap/{__version__}"},
                logger=_WEBSOCKETS_LOGGER,
                max_size=None,
                ping_interval=20,
                ping_timeout=None,
                open_timeout=None,
                close_timeout=5,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            message = f"WebSocket connection failed: {_safe_error_message(exc)}"
        else:
            return _WebSocketConnection(socket)
        raise BAPConnectionError(message)

    def operation_timeout(self, timeout: float | None, cushion: float = 0) -> float:
        resolved = self._default_timeout if timeout is None else timeout
        return resolved + cushion if resolved > 0 else resolved

    def on_message(self, listener: MessageListener) -> Callable[[], None]:
        self._message_listeners[listener] = None

        def unsubscribe() -> None:
            self._message_listeners.pop(listener, None)

        return unsubscribe

    async def send(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> T:
        await asyncio.shield(self.connect())
        self._ensure_connected()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        operation_id = self._start(_Operation(future=cast(asyncio.Future[Any], future)))
        timeout_ms = self.operation_timeout(timeout)
        timer: asyncio.TimerHandle | None = None
        if timeout_ms > 0:
            timer = loop.call_later(
                timeout_ms / 1000,
                self._expire,
                future,
                query,
                timeout_ms,
            )
        try:
            payload: dict[str, Any] = {"query": query}
            if variables:
                payload["variables"] = dict(variables)
            await self._send_frame(
                {"id": operation_id, "type": "subscribe", "payload": payload}
            )
            return await future
        except BAPTimeoutError:
            await self._complete_safely(operation_id)
            raise
        except asyncio.CancelledError:
            await self._complete_safely(operation_id)
            raise
        finally:
            if timer is not None:
                timer.cancel()
            self._stop(operation_id)

    async def subscribe(
        self,
        query: str,
        variables: Mapping[str, Any] | None,
        subscriber: Subscriber,
    ) -> Unsubscribe:
        await asyncio.shield(self.connect())
        self._ensure_connected()
        operation_id = self._start(_Operation(subscriber=subscriber))
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = dict(variables)
        try:
            await self._send_frame(
                {"id": operation_id, "type": "subscribe", "payload": payload}
            )
        except BaseException:
            self._stop(operation_id)
            raise

        async def unsubscribe() -> None:
            if self._operations.pop(operation_id, None) is None:
                return
            await self._send_complete(operation_id)

        return unsubscribe

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._closed = True
        ready = self._ready
        if ready is not None and not ready.done():
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)
        operation_ids = tuple(self._operations)
        if self._connection is not None:
            await asyncio.gather(
                *(
                    self._complete_safely(operation_id)
                    for operation_id in operation_ids
                ),
                return_exceptions=True,
            )
            with suppress(BaseException):
                await _maybe_await(self._connection.close())
        self._fail_all(BAPConnectionError("WebSocket connection closed"))
        self._connected = False
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def __aenter__(self) -> Transport:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    def _start(self, operation: _Operation) -> str:
        self._next_id += 1
        operation_id = str(self._next_id)
        self._operations[operation_id] = operation
        return operation_id

    def _stop(self, operation_id: str) -> None:
        self._operations.pop(operation_id, None)

    def _ensure_connected(self) -> None:
        if self._closed or not self._connected or self._connection is None:
            raise BAPConnectionError("WebSocket is not connected")

    async def _send_frame(self, frame: Mapping[str, Any]) -> None:
        connection = self._connection
        if connection is None:
            raise BAPConnectionError("WebSocket is not connected")
        message = json.dumps(frame, separators=(",", ":"))
        try:
            async with self._send_lock:
                await _maybe_await(connection.send(message))
        except BAPConnectionError:
            raise
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            message = f"WebSocket send failed: {_safe_error_message(exc)}"
        else:
            return
        raise BAPConnectionError(message)

    def _on_frame(self, message: str) -> None:
        try:
            frame = json.loads(message)
        except json.JSONDecodeError:
            logger.debug(
                "Received non-JSON BrowserQL frame; broadcasting it as a raw message"
            )
            self._broadcast(message)
            return
        if isinstance(frame, dict):
            frame_type = frame.get("type")
            if frame_type == "connection_ack" or frame_type == "pong":
                return
            if frame_type == "ping":
                pong: dict[str, Any] = {"type": "pong"}
                if "payload" in frame:
                    pong["payload"] = frame["payload"]
                self._spawn(self._send_frame(pong))
                return
        self._broadcast(message)
        if not isinstance(frame, dict):
            return
        operation_id = frame.get("id")
        if not isinstance(operation_id, str):
            return
        operation = self._operations.get(operation_id)
        if operation is None:
            return
        frame_type = frame.get("type")
        if frame_type == "next":
            payload = frame.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                if operation.subscriber is not None:
                    self._stop(operation_id)
                    self._invoke(operation.subscriber.error, BrowserQLError(errors))
                    self._spawn(self._send_complete(operation_id))
                else:
                    self._operation_error(operation_id, BrowserQLError(errors))
                return
            data = payload.get("data")
            if operation.future is not None and not operation.future.done():
                operation.result = data if data is not None else {}
            elif operation.subscriber is not None:
                self._invoke(operation.subscriber.next, data or {})
        elif frame_type == "error":
            errors = frame.get("payload")
            if not isinstance(errors, list):
                errors = [{"message": "Unknown BrowserQL error"}]
            self._operation_error(operation_id, BrowserQLError(errors))
        elif frame_type == "complete":
            if operation.future is not None and not operation.future.done():
                operation.future.set_result(operation.result)
            if operation.subscriber is not None:
                self._invoke(operation.subscriber.complete)
            self._stop(operation_id)

    def _operation_error(self, operation_id: str, error: Exception) -> None:
        operation = self._operations.get(operation_id)
        if operation is None:
            return
        if operation.future is not None and not operation.future.done():
            operation.future.set_exception(error)
        if operation.subscriber is not None:
            self._invoke(operation.subscriber.error, error)
        self._stop(operation_id)

    def _on_close(self, _event: object | None = None) -> None:
        self._connected = False
        if not self._closing:
            self._closed = True
            self._fail_all(
                BAPConnectionError("WebSocket connection closed unexpectedly")
            )

    def _on_error(self, error: object) -> None:
        self._connected = False
        self._closed = True
        self._fail_all(
            BAPConnectionError(f"WebSocket error: {_safe_error_message(error)}")
        )

    def _fail_all(self, error: Exception) -> None:
        for operation_id, operation in tuple(self._operations.items()):
            if operation.future is not None and not operation.future.done():
                operation.future.set_exception(error)
            if operation.subscriber is not None:
                self._invoke(operation.subscriber.error, error)
            self._stop(operation_id)

    def _broadcast(self, message: str) -> None:
        for listener in tuple(self._message_listeners):
            self._invoke(listener, message)

    def _invoke(self, callback: Callable[..., object], *args: object) -> None:
        try:
            result = callback(*args)
        except BaseException:
            logger.exception("Unhandled exception in bap transport callback")
            return
        if inspect.isawaitable(result):
            self._spawn(_await_callback(result))

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task: asyncio.Task[None] = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Unhandled exception in bap transport callback",
                exc_info=(type(error), error, error.__traceback__),
            )

    def _expire(
        self,
        future: asyncio.Future[Any],
        query: str,
        timeout_ms: float,
    ) -> None:
        if not future.done():
            future.set_exception(BAPTimeoutError(query[:50], timeout_ms))

    async def _send_complete(self, operation_id: str) -> None:
        if self._closed or self._connection is None:
            return
        with suppress(BAPConnectionError):
            await self._send_frame({"id": operation_id, "type": "complete"})

    async def _complete_safely(self, operation_id: str) -> None:
        if operation_id not in self._operations or self._connection is None:
            return
        with suppress(BaseException):
            await asyncio.shield(
                self._send_frame({"id": operation_id, "type": "complete"})
            )


async def _maybe_await(result: MaybeAwaitable) -> None:
    if inspect.isawaitable(result):
        await result


async def _await_callback(awaitable: Awaitable[object]) -> None:
    await awaitable


def _safe_error_message(error: object) -> str:
    return _redact(str(error) or type(error).__name__)


def _redact(message: str) -> str:
    message = re.sub(
        r"([?&]token=)[^&\s]+",
        r"\1<redacted>",
        message,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@",
        r"\1<redacted>@",
        message,
        flags=re.IGNORECASE,
    )
