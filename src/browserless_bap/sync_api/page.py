"""Synchronous Page facade."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Self, cast

from .._unset import UNSET, UnsetType
from ..element_handle import ElementHandle as AsyncElementHandle
from ..types.enums import (
    Method,
    OperatorType,
    ResourceType,
    WaitForFunctionPolling,
    WaitUntilGoto,
)
from ..types.inputs import CookieInput
from ..types.responses import (
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
from ._base import SyncBase
from ._bridge import CallbackDispatcher
from ._page_generated import PageGenerated
from .element_handle import ElementHandle

Callback = Callable[[object], object]
_SUBSCRIPTION_START_TIMEOUT = 5.0
_CALLBACK_QUEUE_SIZE = 1024


class Page(PageGenerated, SyncBase[Any]):
    def __init__(self, impl: Any, bridge: Any = None) -> None:
        SyncBase.__init__(self, impl, bridge)
        self._event_wrappers: dict[tuple[str, Callback, bool], Callback] = {}
        self._listeners_lock = threading.Lock()
        self._dispatcher: CallbackDispatcher | None = None
        self._dispatcher_closed = False

    @property
    def closed(self) -> bool:
        return bool(self._impl.closed)

    def _wrap_result(self, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, AsyncElementHandle):
            return ElementHandle(value, self._bridge)
        if (
            isinstance(value, list)
            and value
            and all(isinstance(item, AsyncElementHandle) for item in value)
        ):
            return [ElementHandle(item, self._bridge) for item in value]
        return value

    def _invoke(self, method_name: str, *args: object, **kwargs: object) -> object:
        return self._wrap_result(super()._invoke(method_name, *args, **kwargs))

    def wait_for_live_complete(
        self, *, timeout: float | None = None
    ) -> LiveURLCompleteEvent:
        """Wait for the current handoff; timeout is in milliseconds (0 disables it)."""
        return cast(
            LiveURLCompleteEvent,
            self._invoke("wait_for_live_complete", timeout=timeout),
        )

    def subscribe(self, listener: Callback) -> Callable[[], None]:
        self.on("message", listener)

        def unsubscribe() -> None:
            self.off("message", listener)

        return unsubscribe

    def listener_count(self, event: str) -> int:
        """Return the number of listeners registered for `event`."""

        return cast(int, self._invoke("listener_count", event))

    def _callback_wrapper(
        self,
        event: str,
        callback: Callback,
        *,
        once: bool = False,
    ) -> Callback:
        key = (event, callback, once)

        def route_error(error: BaseException) -> None:
            async def emit_error() -> None:
                self._impl.emit("error", error)

            self._bridge.submit(emit_error())

        def dispatch(payload: object) -> None:
            with self._listeners_lock:
                if once and key not in self._event_wrappers:
                    return
                dispatcher = self._dispatcher
                queued = dispatcher is not None and dispatcher.submit(
                    callback,
                    payload,
                    on_error=route_error if event != "error" else None,
                )
                if once and queued:
                    self._event_wrappers.pop(key, None)
                    self._impl.off(event, dispatch)

        with self._listeners_lock:
            existing = self._event_wrappers.get(key)
            if existing is not None:
                return existing
            if self._dispatcher is None and not self._dispatcher_closed:
                self._dispatcher = self._bridge.new_dispatcher(
                    max_queue_size=_CALLBACK_QUEUE_SIZE
                )
            self._event_wrappers[key] = dispatch
            return dispatch

    def _wait_for_subscription(self, event: str) -> None:
        waiter = getattr(self._impl, "_wait_subscription_started", None)
        if waiter is None:
            return
        try:
            self._bridge.run(
                cast(Any, waiter(event)),
                timeout=_SUBSCRIPTION_START_TIMEOUT,
            )
        except Exception:
            # Establishment is bounded and best-effort. The async Page owns
            # routing a real subscription failure to its ``error`` event.
            return

    def on(self, event: str, callback: Callback) -> Self:
        wrapper = self._callback_wrapper(event, callback)
        self._invoke("on", event, wrapper)
        self._wait_for_subscription(event)
        return self

    def once(self, event: str, callback: Callback) -> Self:
        wrapper = self._callback_wrapper(event, callback, once=True)
        self._invoke("on", event, wrapper)
        self._wait_for_subscription(event)
        return self

    def off(self, event: str, callback: Callback) -> Self:
        with self._listeners_lock:
            keys = [key for key in self._event_wrappers if key[:2] == (event, callback)]
            wrappers = [
                wrapper
                for wrapper in (self._event_wrappers.pop(key, None) for key in keys)
                if wrapper is not None
            ]
        for wrapper in wrappers or [callback]:
            self._invoke("off", event, wrapper)
        return self

    def emit(self, event: str, payload: object) -> bool:
        return bool(self._invoke("emit", event, payload))

    def remove_all_listeners(self, event: str | None = None) -> Self:
        with self._listeners_lock:
            if event is None:
                self._event_wrappers.clear()
            else:
                for key in [key for key in self._event_wrappers if key[0] == event]:
                    self._event_wrappers.pop(key, None)
        self._invoke("remove_all_listeners", event)
        return self

    def goto(
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
        return cast(
            HTTPResponse | None,
            self._invoke(
                "goto",
                url,
                timeout=timeout,
                wait_until=wait_until,
                wait_until_all=wait_until_all,
                referer=referer,
                referrer_policy=referrer_policy,
                remote_response_metadata=remote_response_metadata,
            ),
        )

    def response(
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
        return cast(
            list[ResponseResponse],
            self._invoke(
                "response",
                status=status,
                method=method,
                operator=operator,
                timeout=timeout,
                type=type,
                url=url,
                wait=wait,
                body=body,
                body_encoding=body_encoding,
            ),
        )

    def select_option(
        self, selector: str, value: str | Sequence[str]
    ) -> SelectResponse:
        return cast(SelectResponse, self._invoke("select_option", selector, value))

    def add_cookies(self, cookies: Sequence[CookieInput]) -> CookieResponse:
        return cast(CookieResponse, self._invoke("add_cookies", cookies))

    def set_extra_http_headers(self, headers: Mapping[str, str]) -> HTTPHeadersResponse:
        return cast(
            HTTPHeadersResponse, self._invoke("set_extra_http_headers", headers)
        )

    def evaluate(
        self,
        expression: str,
        *,
        timeout: float | UnsetType = UNSET,
        url: str | UnsetType = UNSET,
    ) -> str | None:
        return cast(
            str | None,
            self._invoke("evaluate", expression, timeout=timeout, url=url),
        )

    def wait_for_function(
        self,
        expression: str,
        *,
        polling: float | UnsetType = UNSET,
        polling_type: WaitForFunctionPolling | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
        complete_on_promise_resolution: bool | UnsetType = UNSET,
    ) -> WaitForFunction:
        return cast(
            WaitForFunction,
            self._invoke(
                "wait_for_function",
                expression,
                polling=polling,
                polling_type=polling_type,
                timeout=timeout,
                complete_on_promise_resolution=complete_on_promise_resolution,
            ),
        )

    def wait_for_event(
        self,
        event: str,
        *,
        timeout: float | UnsetType = UNSET,
    ) -> WaitForEvent:
        """Wait for the next event payload, bounded by `timeout` when provided."""

        return cast(
            WaitForEvent, self._invoke("wait_for_event", event, timeout=timeout)
        )

    def add_script_tag(
        self,
        *,
        url: str | UnsetType = UNSET,
        path: str | Path | UnsetType = UNSET,
        content: str | UnsetType = UNSET,
        id: str | UnsetType = UNSET,
        type: str | UnsetType = UNSET,
    ) -> AddScriptTagResponse:
        return cast(
            AddScriptTagResponse,
            self._invoke(
                "add_script_tag",
                url=url,
                path=path,
                content=content,
                id=id,
                type=type,
            ),
        )

    def add_style_tag(
        self,
        *,
        url: str | UnsetType = UNSET,
        path: str | Path | UnsetType = UNSET,
        content: str | UnsetType = UNSET,
    ) -> AddStyleTagResponse:
        return cast(
            AddStyleTagResponse,
            self._invoke("add_style_tag", url=url, path=path, content=content),
        )

    def wait_for_request(
        self,
        url: str | UnsetType = UNSET,
        *,
        method: Method | UnsetType = UNSET,
        operator: OperatorType | UnsetType = UNSET,
        timeout: float | UnsetType = UNSET,
    ) -> WaitForRequestResponse:
        return cast(
            WaitForRequestResponse,
            self._invoke(
                "wait_for_request",
                url,
                method=method,
                operator=operator,
                timeout=timeout,
            ),
        )

    def wait_for_response(
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
            self._invoke(
                "wait_for_response",
                url,
                statuses=statuses,
                codes=codes,
                operator=operator,
                timeout=timeout,
            ),
        )

    def wait_for_timeout(self, ms: float) -> None:
        self._invoke("wait_for_timeout", ms)

    def send(
        self,
        query: str,
        *,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._invoke(
            "send",
            query,
            variables=variables,
            timeout=timeout,
        )

    def close(self) -> None:
        try:
            self._invoke("close")
        finally:
            with self._listeners_lock:
                self._event_wrappers.clear()
            self._close_dispatcher()

    def _close_dispatcher(self, *, wait: bool = True) -> CallbackDispatcher | None:
        with self._listeners_lock:
            dispatcher, self._dispatcher = self._dispatcher, None
            self._dispatcher_closed = True
        if dispatcher is not None:
            dispatcher.close(wait=wait)
        return dispatcher

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()
