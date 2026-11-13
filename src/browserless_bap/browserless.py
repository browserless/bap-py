"""Public entry point for creating BAP-backed browser sessions."""

from __future__ import annotations

from .browser import Browser
from .transport import TransportFactory


class Browserless:
    """Factory namespace matching the Browserless SDKs."""

    def __new__(cls) -> Browserless:
        raise TypeError("Browserless is a factory and cannot be instantiated")

    @staticmethod
    def connect(
        *,
        browser_ws_endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 30_000,
        transport: TransportFactory | None = None,
        connect_timeout: float | None = None,
    ) -> Browser:
        """Create a browser configured for a BAP-compatible WebSocket endpoint.

        ``connect_timeout`` bounds opening the connection in ms; defaults to
        ``timeout``; 0 disables it.
        """

        return Browser(
            browser_ws_endpoint=browser_ws_endpoint,
            token=token,
            timeout=timeout,
            transport=transport,
            connect_timeout=connect_timeout,
        )
