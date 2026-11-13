"""Synchronous package entry point."""

from __future__ import annotations

from typing import Any, Never

from browserless_bap.browserless import Browserless as AsyncBrowserless

from ._bridge import get_loop_thread
from .browser import Browser


class Browserless:
    def __new__(cls, *args: object, **kwargs: object) -> Never:
        raise TypeError("Browserless is a namespace; call Browserless.connect(...)")

    @staticmethod
    def connect(
        *,
        browser_ws_endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 30_000,
        transport: Any = None,
        connect_timeout: float | None = None,
    ) -> Browser:
        bridge = get_loop_thread()
        impl = AsyncBrowserless.connect(
            browser_ws_endpoint=browser_ws_endpoint,
            token=token,
            timeout=timeout,
            transport=transport,
            connect_timeout=connect_timeout,
        )
        bridge.track_browser(impl)
        return Browser(impl, bridge)
