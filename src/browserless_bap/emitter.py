"""Small insertion-ordered event emitter used by :class:`browserless_bap.Page`."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

Listener: TypeAlias = Callable[[Any], object]
CountChangeHook: TypeAlias = Callable[[str, int], None]
logger = logging.getLogger("browserless_bap")


class EventEmitter:
    """An ordered, deduplicating emitter with async-listener support."""

    def __init__(self, on_count_change: CountChangeHook | None = None) -> None:
        self._listeners: dict[str, dict[Listener, None]] = {}
        self._once_originals: dict[Listener, Listener] = {}
        self._on_count_change = on_count_change
        self._tasks: set[asyncio.Task[None]] = set()

    def on(self, event: str, listener: Listener) -> EventEmitter:
        listeners = self._listeners.setdefault(event, {})
        previous = len(listeners)
        listeners[listener] = None
        if len(listeners) != previous:
            self._notify_count(event, len(listeners))
        return self

    def off(self, event: str, listener: Listener) -> EventEmitter:
        listeners = self._listeners.get(event)
        if listeners is None:
            return self
        targets = [
            candidate
            for candidate in listeners
            if candidate is listener or self._once_originals.get(candidate) is listener
        ]
        if not targets:
            return self
        for target in targets:
            del listeners[target]
            self._once_originals.pop(target, None)
        count = len(listeners)
        if not listeners:
            del self._listeners[event]
        self._notify_count(event, count)
        return self

    def once(self, event: str, listener: Listener) -> EventEmitter:
        if any(
            self._once_originals.get(candidate) is listener
            for candidate in self._listeners.get(event, ())
        ):
            return self

        def wrapper(payload: object) -> object:
            # Remove before invocation so a re-entrant emit cannot fire twice.
            self.off(event, wrapper)
            return listener(payload)

        self._once_originals[wrapper] = listener
        return self.on(event, wrapper)

    def emit(self, event: str, payload: object) -> bool:
        listeners = self._listeners.get(event)
        if not listeners:
            return False
        for listener in tuple(listeners):
            try:
                result = listener(payload)
            except BaseException as exc:
                self._route_listener_error(event, exc)
                continue
            if inspect.isawaitable(result):
                self._schedule_listener(event, result)
        return True

    def listener_count(self, event: str) -> int:
        return len(self._listeners.get(event, ()))

    def remove_all_listeners(self, event: str | None = None) -> EventEmitter:
        events = (event,) if event is not None else tuple(self._listeners)
        for current in events:
            if current in self._listeners:
                for listener in self._listeners[current]:
                    self._once_originals.pop(listener, None)
                del self._listeners[current]
                self._notify_count(current, 0)
        return self

    def _notify_count(self, event: str, count: int) -> None:
        if self._on_count_change is not None:
            self._on_count_change(event, count)

    def _schedule_listener(self, event: str, awaitable: Awaitable[object]) -> None:
        async def run() -> None:
            try:
                await awaitable
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                self._route_listener_error(event, exc)

        scheduled = run()
        try:
            task = asyncio.create_task(scheduled)
        except RuntimeError:
            scheduled.close()
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            self._route_listener_error(
                event,
                RuntimeError("Async event listener requires a running event loop"),
            )
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _route_listener_error(self, source_event: str, error: BaseException) -> None:
        if source_event == "error":
            logger.error(
                "Unhandled exception in bap error event listener",
                exc_info=(type(error), error, error.__traceback__),
            )
            return
        if not self.emit("error", error):
            logger.error(
                "Unhandled bap event listener exception",
                exc_info=(type(error), error, error.__traceback__),
            )
