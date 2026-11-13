"""Concrete BAP page runtime and handwritten ergonomic methods."""

# Remote-operation timeouts are intentional public API parameters.
# ruff: noqa: ASYNC109

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self, cast

from ._codec import drop_unset as _drop_unset
from ._io import read_text_file
from ._page_generated import PageGenerated
from ._unset import UNSET, UnsetType
from .emitter import EventEmitter, Listener
from .errors import BAPConnectionError, BAPTimeoutError, BAPValueError
from .graphql.builder import build_operation, selection_for
from .graphql.mutations import ARG_TYPES
from .graphql.subscriptions import SUBSCRIPTIONS
from .transport import (
    OPERATION_TIMEOUT_CUSHION_MS,
    Subscriber,
    Transport,
    Unsubscribe,
)
from .types.enums import (
    Method,
    OperatorType,
    ResourceType,
    WaitForFunctionPolling,
    WaitUntilGoto,
)
from .types.events import PageEventsMixin
from .types.inputs import CookieInput
from .types.responses import (
    AddScriptTagResponse,
    AddStyleTagResponse,
    CookieResponse,
    HTTPHeadersResponse,
    HTTPResponse,
    LiveURLCompleteEvent,
    ResponseResponse,
    SelectResponse,
    WaitForEvent,
    WaitForFunction,
    WaitForRequestResponse,
    WaitForResponseResponse,
)


@dataclass
class _LiveHandoff:
    future: asyncio.Future[LiveURLCompleteEvent]
    id: str | None = None
    waiters: int = 0
    early: dict[str, LiveURLCompleteEvent] = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return self.future.done() and (
            self.future.cancelled() or self.future.exception() is not None
        )


def _live_handoff() -> _LiveHandoff:
    future: asyncio.Future[LiveURLCompleteEvent] = (
        asyncio.get_running_loop().create_future()
    )
    # Retrieve errors even when completion precedes the caller's wait.
    future.add_done_callback(
        lambda done: None if done.cancelled() else done.exception()
    )
    return _LiveHandoff(future)


class Page(PageGenerated, PageEventsMixin):
    """A BAP page with generated methods and an event lifecycle."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._closed_flag = False
        self._live: _LiveHandoff | None = None
        self._previous_live: list[_LiveHandoff] = []
        self._minting = False
        self._events = EventEmitter(self._on_listener_count_change)
        self._unsubscribes: dict[str, Unsubscribe] = {}
        self._starting: set[str] = set()
        self._restart_after_start: set[str] = set()
        self._subscription_ready: dict[str, asyncio.Event] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._detach_transport = transport.on_message(
            lambda message: self._events.emit("message", message)
        )

    @property
    def closed(self) -> bool:
        return self._closed_flag or self._transport.closed

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Listen to every non-handshake raw transport frame."""

        self._events.on("message", listener)

        def unsubscribe() -> None:
            self._events.off("message", listener)

        return unsubscribe

    def _on(self, event: str, listener: Listener) -> None:
        self._events.on(event, listener)

    def _once(self, event: str, listener: Listener) -> None:
        self._events.once(event, listener)

    def _off(self, event: str, listener: Listener) -> None:
        self._events.off(event, listener)

    def emit(self, event: str, payload: object) -> bool:
        return self._events.emit(event, payload)

    def listener_count(self, event: str) -> int:
        return self._events.listener_count(event)

    def remove_all_listeners(self, event: str | None = None) -> Self:
        self._events.remove_all_listeners(event)
        return self

    async def _execute(
        self,
        mutation_name: str,
        args: Mapping[str, Any] | None,
        response_type: str,
        *,
        timeout: float | UnsetType | None = None,
        opt_in: Sequence[str] = (),
    ) -> Any:
        if mutation_name != "liveURL":
            return await self._execute_operation(
                mutation_name, args, response_type, timeout=timeout, opt_in=opt_in
            )
        if self._minting:
            raise BAPValueError(
                "Await the previous live_url() call before minting another link"
            )
        self._minting = True
        if self._live and self._live.id and not self._live.future.done():
            self._previous_live.append(self._live)
        state = (
            self._live
            if self._live and not self._live.id and not self._live.future.done()
            else _live_handoff()
        )
        self._live = state
        try:
            self._on_listener_count_change("liveComplete", 1)
            await self._wait_subscription_started("liveComplete")
            if "liveComplete" not in self._unsubscribes:
                raise BAPConnectionError("Live completion subscription unavailable")
            result = await self._execute_operation(
                mutation_name, args, response_type, timeout=timeout, opt_in=opt_in
            )
            state.id = result.get("liveURLId") if isinstance(result, Mapping) else None
            if not state.id:
                raise BAPValueError("live_url returned no liveURLId")
            if state.id in state.early and not state.future.done():
                state.future.set_result(state.early[state.id])
            return result
        except BaseException as error:
            if not state.future.done():
                state.future.set_exception(
                    error
                    if isinstance(error, Exception)
                    else BAPConnectionError("live_url() was cancelled or interrupted")
                )
            raise
        finally:
            state.early.clear()
            self._minting = False
            self._on_listener_count_change(
                "liveComplete", self.listener_count("liveComplete")
            )

    async def _execute_operation(
        self,
        mutation_name: str,
        args: Mapping[str, Any] | None,
        response_type: str,
        *,
        timeout: float | UnsetType | None = None,
        opt_in: Sequence[str] = (),
    ) -> Any:
        fields = selection_for(response_type, opt_in)
        operation = build_operation(
            mutation_name,
            args,
            fields,
            ARG_TYPES.get(mutation_name),
        )
        query, variables = operation
        operation_timeout = _timeout_value(timeout)
        if "timeout" in ARG_TYPES.get(mutation_name, {}):
            operation_timeout = self._transport.operation_timeout(
                operation_timeout, OPERATION_TIMEOUT_CUSHION_MS
            )
        result: Any = await self._transport.send(
            query,
            variables,
            operation_timeout,
        )
        if not isinstance(result, Mapping):
            return None
        return result.get(mutation_name)

    async def wait_for_live_complete(
        self, *, timeout: float | None = None
    ) -> LiveURLCompleteEvent:
        """Wait for the current handoff or next mint.

        Timeout is in ms; None or 0 disables the client deadline.

        Completion or failure is retained until the next live_url() call.
        """
        if self.closed:
            raise BAPConnectionError("Page is closed")
        deadline = 0 if timeout is None else timeout
        if not math.isfinite(deadline) or deadline < 0:
            raise BAPValueError("timeout must be a finite non-negative number")
        if self._live is None or (
            self._live.rejected and not self._live.id and not self._minting
        ):
            self._live = _live_handoff()
        state = self._live
        state.waiters += 1
        if not state.future.done():
            self._on_listener_count_change("liveComplete", 1)
        try:
            # Each waiter has its own deadline; cancellation must not cancel
            # the retained completion or another caller's wait.
            async with asyncio.timeout(deadline / 1000 if deadline else None):
                return await asyncio.shield(state.future)
        except BAPTimeoutError:
            raise
        except TimeoutError as error:
            raise BAPTimeoutError("wait_for_live_complete", deadline) from error
        finally:
            state.waiters -= 1
            if (
                self._live is state
                and not state.id
                and not state.future.done()
                and not state.waiters
                and not self._minting
            ):
                self._live = None
            self._on_listener_count_change(
                "liveComplete", self.listener_count("liveComplete")
            )

    def _fail_live(self, error: BaseException) -> None:
        for state in (self._live, *self._previous_live):
            if state is not None and not state.future.done():
                state.future.set_exception(error)
        self._previous_live.clear()

    def _deliver_subscription(self, event: str, data: Mapping[str, Any]) -> None:
        if event == "liveComplete":
            completion = cast(LiveURLCompleteEvent, data[event])
            # Reused IDs complete the oldest pending handoff first.
            state = next(
                (
                    previous
                    for previous in self._previous_live
                    if previous.id == completion["liveURLId"]
                ),
                self._live,
            )
            if (
                state
                and not state.future.done()
                and state.id == completion["liveURLId"]
            ):
                state.future.set_result(completion)
            elif state and not state.id and self._minting:
                completion_id = completion["liveURLId"]
                if completion_id is not None:
                    state.early[completion_id] = completion
            self._previous_live = [
                state for state in self._previous_live if not state.future.done()
            ]
        self._events.emit(event, data.get(event))
        if event == "liveComplete":
            self._on_listener_count_change(event, self.listener_count(event))

    async def goto(
        self,
        url: str,
        *,
        timeout: float | UnsetType = UNSET,
        wait_until: WaitUntilGoto | UnsetType = UNSET,
        wait_until_all: list[WaitUntilGoto] | UnsetType = UNSET,
        referer: str | UnsetType = UNSET,
        referrer_policy: str | UnsetType = UNSET,
        remote_response_metadata: bool | UnsetType = UNSET,
    ) -> HTTPResponse | None:
        """Navigate to a URL with optional waitUntil and timeout parameters."""
        args = _drop_unset(
            {
                "url": url,
                "timeout": timeout,
                "waitUntil": wait_until,
                "waitUntilAll": wait_until_all,
                "referer": referer,
                "referrerPolicy": referrer_policy,
            }
        )
        return cast(
            HTTPResponse | None,
            await self._execute(
                "goto",
                args,
                "HTTPResponse",
                timeout=timeout,
                opt_in=("remoteMetadata",) if remote_response_metadata is True else (),
            ),
        )

    async def response(
        self,
        *,
        status: list[int] | UnsetType = UNSET,
        method: list[Method] | UnsetType = UNSET,
        operator: OperatorType | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
        type: list[ResourceType] | UnsetType = UNSET,
        url: list[str] | UnsetType = UNSET,
        wait: bool | UnsetType = UNSET,
        body: bool | UnsetType = UNSET,
        body_encoding: bool | UnsetType = UNSET,
    ) -> list[ResponseResponse]:
        """List responses; fetch bodies only with body=True.

        body_encoding=True implies body=True and adds the base64Encoded flag.
        """
        args = _drop_unset(
            {
                "status": status,
                "method": method,
                "operator": operator,
                "timeout": timeout,
                "type": type,
                "url": url,
                "wait": wait,
            }
        )
        opt_in = (
            ("bodyEncoding",)
            if body_encoding is True
            else ("body",)
            if body is True
            else ()
        )
        result = await self._execute(
            "response", args, "ResponseResponse", timeout=timeout, opt_in=opt_in
        )
        return cast(list[ResponseResponse], list(result or ()))

    async def select_option(
        self, selector: str, value: str | Sequence[str]
    ) -> SelectResponse:
        return cast(
            SelectResponse,
            await self._execute(
                "select",
                {"selector": selector, "value": value},
                "SelectResponse",
            ),
        )

    async def add_cookies(self, cookies: Sequence[CookieInput]) -> CookieResponse:
        return cast(
            CookieResponse,
            await self._execute(
                "cookies", {"cookies": list(cookies)}, "CookieResponse"
            ),
        )

    async def set_extra_http_headers(
        self, headers: Mapping[str, str]
    ) -> HTTPHeadersResponse:
        values = [{"name": name, "value": value} for name, value in headers.items()]
        return cast(
            HTTPHeadersResponse,
            await self._execute(
                "setExtraHTTPHeaders",
                {"headers": values},
                "HTTPHeadersResponse",
            ),
        )

    async def evaluate(
        self,
        expression: str,
        *,
        timeout: float | UnsetType = UNSET,
        url: str | UnsetType = UNSET,
    ) -> str | None:
        result = await self._execute(
            "evaluate",
            _drop_unset({"content": expression, "timeout": timeout, "url": url}),
            "EvaluateResponse",
            timeout=timeout,
        )
        if not isinstance(result, Mapping):
            return None
        value = result.get("value")
        return None if value is None else str(value)

    async def wait_for_function(
        self,
        expression: str,
        *,
        polling: float | UnsetType = UNSET,
        polling_type: WaitForFunctionPolling | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
        complete_on_promise_resolution: bool | UnsetType = UNSET,
    ) -> WaitForFunction:
        predicate = expression
        if complete_on_promise_resolution is True:
            predicate = f"async () => {{ await ({expression})(); return true; }}"
        args = _drop_unset(
            {
                "fn": predicate,
                "polling": polling,
                "pollingType": polling_type,
                "timeout": timeout,
            }
        )
        return cast(
            WaitForFunction,
            await self._execute(
                "waitForFunction",
                args,
                "WaitForFunction",
                timeout=timeout,
            ),
        )

    async def wait_for_event(
        self,
        event: str,
        *,
        timeout: float | UnsetType = UNSET,
    ) -> WaitForEvent:
        """Wait for the next event payload, bounded by `timeout` when provided."""

        return cast(
            WaitForEvent,
            await self._execute(
                "waitForEvent",
                _drop_unset({"event": event, "timeout": timeout}),
                "WaitForEvent",
                timeout=timeout,
            ),
        )

    async def add_script_tag(
        self,
        *,
        url: str | UnsetType = UNSET,
        path: str | Path | UnsetType = UNSET,
        content: str | UnsetType = UNSET,
        id: str | UnsetType = UNSET,
        type: str | UnsetType = UNSET,
    ) -> AddScriptTagResponse:
        _require_one_source(url=url, path=path, content=content)
        resolved_content = content
        if path is not UNSET:
            raw_path = str(path)
            resolved_content = await read_text_file(raw_path)
            safe_path = re.sub(r"[\r\n\u2028\u2029]", "", raw_path)
            resolved_content += f"//# sourceURL={safe_path}"
        args = _drop_unset(
            {
                "url": url,
                "content": resolved_content,
                "id": id,
                "type": "text/javascript" if type is UNSET else type,
            }
        )
        return cast(
            AddScriptTagResponse,
            await self._execute("addScriptTag", args, "AddScriptTagResponse"),
        )

    async def add_style_tag(
        self,
        *,
        url: str | UnsetType = UNSET,
        path: str | Path | UnsetType = UNSET,
        content: str | UnsetType = UNSET,
    ) -> AddStyleTagResponse:
        _require_one_source(url=url, path=path, content=content)
        resolved_content = content
        if path is not UNSET:
            raw_path = str(path)
            resolved_content = await read_text_file(raw_path)
            safe_path = raw_path.replace("*/", "")
            resolved_content += f"/*# sourceURL={safe_path}*/"
        return cast(
            AddStyleTagResponse,
            await self._execute(
                "addStyleTag",
                _drop_unset({"url": url, "content": resolved_content}),
                "AddStyleTagResponse",
            ),
        )

    async def wait_for_request(
        self,
        url: str | UnsetType = UNSET,
        *,
        method: Method | UnsetType = UNSET,
        operator: OperatorType | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
    ) -> WaitForRequestResponse:
        return cast(
            WaitForRequestResponse,
            await self._execute(
                "waitForRequest",
                _drop_unset(
                    {
                        "url": url,
                        "method": method,
                        "operator": operator,
                        "timeout": timeout,
                    }
                ),
                "WaitForRequestResponse",
                timeout=timeout,
            ),
        )

    async def wait_for_response(
        self,
        url: str | UnsetType = UNSET,
        *,
        statuses: Sequence[int] | UnsetType = UNSET,
        codes: Sequence[int] | UnsetType = UNSET,
        operator: OperatorType | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
    ) -> WaitForResponseResponse:
        return cast(
            WaitForResponseResponse,
            await self._execute(
                "waitForResponse",
                _drop_unset(
                    {
                        "url": url,
                        "statuses": statuses,
                        "codes": codes,
                        "operator": operator,
                    }
                ),
                "WaitForResponseResponse",
                timeout=timeout,
            ),
        )

    async def wait_for_timeout(self, ms: float) -> None:
        await self._execute(
            "waitForTimeout",
            {"time": ms},
            "WaitForTimeoutResponse",
            timeout=ms + OPERATION_TIMEOUT_CUSHION_MS,
        )

    async def send(
        self,
        query: str,
        *,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return await self._transport.send(query, variables, timeout)

    async def close(self) -> None:
        if self._closed_flag:
            return
        self._closed_flag = True
        self._fail_live(BAPConnectionError("Page is closed"))
        for ready in self._subscription_ready.values():
            ready.set()
        self._detach_transport()
        self._events.remove_all_listeners()
        unsubscribes = tuple(self._unsubscribes.values())
        self._unsubscribes.clear()
        try:
            async with asyncio.timeout(5):
                await asyncio.gather(
                    *(unsubscribe() for unsubscribe in unsubscribes),
                    *tuple(self._tasks),
                    return_exceptions=True,
                )
        except TimeoutError:
            for task in tuple(self._tasks):
                task.cancel()
        await self._transport.close()

    async def __aenter__(self) -> Page:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    @property
    def _has_pending_live(self) -> bool:
        return self._minting or bool(
            (
                self._live
                and not self._live.future.done()
                and (self._live.id or self._live.waiters)
            )
            or self._previous_live
        )

    def _on_listener_count_change(self, event: str, count: int) -> None:
        if self._closed_flag or event not in SUBSCRIPTIONS:
            return
        if count > 0:
            if event in self._unsubscribes:
                self._subscription_ready.setdefault(event, asyncio.Event()).set()
            elif event not in self._starting:
                self._starting.add(event)
                self._subscription_ready[event] = asyncio.Event()
                self._spawn(self._start_subscription(event))
            elif count == 1:
                self._restart_after_start.add(event)
        else:
            if event == "liveComplete" and self._has_pending_live:
                return
            self._restart_after_start.discard(event)
            self._spawn(self._stop_subscription(event))

    async def _wait_subscription_started(self, event: str) -> None:
        """Wait until a lazy subscription start attempt reaches a terminal state."""

        if (
            self._closed_flag
            or (
                self._events.listener_count(event) == 0
                and not (event == "liveComplete" and self._has_pending_live)
            )
            or event in self._unsubscribes
        ):
            return
        ready = self._subscription_ready.get(event)
        if ready is not None:
            await ready.wait()

    async def _start_subscription(self, event: str) -> None:
        if event in self._unsubscribes or self._closed_flag:
            self._starting.discard(event)
            ready = self._subscription_ready.get(event)
            if ready is not None:
                ready.set()
            return
        own_handle: Unsubscribe | None = None
        terminated = False

        def clear_if_own() -> None:
            nonlocal terminated
            terminated = True
            if own_handle is not None and self._unsubscribes.get(event) is own_handle:
                self._unsubscribes.pop(event, None)

        def on_error(error: Exception) -> None:
            clear_if_own()
            if event == "liveComplete":
                self._fail_live(error)
            self._events.emit("error", error)

        def on_complete() -> None:
            clear_if_own()
            if event == "liveComplete":
                self._fail_live(BAPConnectionError("Live completion stream ended"))

        try:
            spec = SUBSCRIPTIONS[event]
            operation = build_operation(
                event,
                None,
                spec["fields"],
                spec["arg_types"],
                "subscription",
            )
            query, variables = operation
            unsubscribe = await self._transport.subscribe(
                query,
                variables,
                Subscriber(
                    next=lambda data: self._deliver_subscription(event, data),
                    error=on_error,
                    complete=on_complete,
                ),
            )
            own_handle = unsubscribe
            if (
                terminated
                or self._closed_flag
                or (
                    self._events.listener_count(event) == 0
                    and not (event == "liveComplete" and self._has_pending_live)
                )
            ):
                await unsubscribe()
                return
            self._unsubscribes[event] = unsubscribe
        except BaseException as exc:
            if event == "liveComplete":
                self._fail_live(exc)
            if not self._closed_flag:
                self._events.emit("error", exc)
        finally:
            self._starting.discard(event)
            ready = self._subscription_ready.get(event)
            if ready is not None:
                ready.set()
            restart = event in self._restart_after_start
            self._restart_after_start.discard(event)
            if (
                restart
                and not self._closed_flag
                and self._events.listener_count(event) > 0
                and event not in self._unsubscribes
            ):
                self._starting.add(event)
                self._subscription_ready[event] = asyncio.Event()
                self._spawn(self._start_subscription(event))

    async def _stop_subscription(self, event: str) -> None:
        if self._events.listener_count(event) > 0 or (
            event == "liveComplete" and self._has_pending_live
        ):
            return
        unsubscribe = self._unsubscribes.pop(event, None)
        if unsubscribe is not None:
            await unsubscribe()

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and not self._closed_flag:
            self._events.emit("error", error)


def _timeout_value(value: float | UnsetType | None) -> float | None:
    return None if value is UNSET else value


def _require_one_source(
    *,
    url: str | UnsetType,
    path: str | Path | UnsetType,
    content: str | UnsetType,
) -> None:
    values = (url, path, content)
    if sum(value is not UNSET for value in values) != 1:
        raise BAPValueError(
            "Exactly one of `url`, `path`, or `content` must be specified."
        )
