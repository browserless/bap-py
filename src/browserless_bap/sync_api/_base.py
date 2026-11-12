"""Shared machinery for synchronous wrappers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar, cast

from ._bridge import LoopThread, get_loop_thread

T = TypeVar("T")


class SyncBase(Generic[T]):
    """Wrap one async implementation object on the process-global bridge."""

    def __init__(self, impl: T, bridge: LoopThread | None = None) -> None:
        self._impl = impl
        self._bridge = bridge or get_loop_thread()

    def _invoke(self, method_name: str, *args: object, **kwargs: object) -> Any:
        target = cast(Callable[..., object], getattr(self._impl, method_name))

        async def invoke() -> object:
            # Even synchronous helpers such as Page.on() must execute on the
            # bridge loop: they can schedule asyncio tasks as a side effect.
            result = target(*args, **kwargs)
            if inspect.isawaitable(result):
                return await cast(Awaitable[object], result)
            return result

        return self._bridge.run(invoke())
