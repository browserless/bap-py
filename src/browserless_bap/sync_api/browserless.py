"""Synchronous package entry point."""

from __future__ import annotations

from browserless_bap.browserless import Browserless as AsyncBrowserless
from browserless_bap.transport import TransportFactory

from ._bridge import get_loop_thread
from .browser import Browser


class Browserless:
    """Factory namespace for blocking browser sessions."""

    def __new__(cls) -> Browserless:
        raise TypeError("Browserless is a namespace; call Browserless.connect(...)")

    @staticmethod
    def connect(
        *,
        browser_ws_endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 30_000,
        transport: TransportFactory | None = None,
        connect_timeout: float | None = None,
    ) -> Browser:
        """Create a blocking browser for a BAP-compatible WebSocket endpoint."""

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
