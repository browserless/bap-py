"""Browser lifecycle for BAP-backed pages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import ValueError
from .page import Page
from .transport import Transport, TransportFactory

logger = logging.getLogger("browserless_bap")


class Browser:
    """Owns the pages opened against one Browserless configuration."""

    def __init__(
        self,
        *,
        browser_ws_endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 30_000,
        transport: TransportFactory | None = None,
    ) -> None:
        if browser_ws_endpoint is None and transport is None:
            raise ValueError(
                "Either `browser_ws_endpoint` or `transport` must be provided"
            )
        self._base_url = browser_ws_endpoint
        self._token = token
        self._timeout = timeout
        self._transport_factory = transport
        self._pages: list[Page] = []
        self._closed = False

    async def new_page(self) -> Page:
        """Open a new page with its own BAP WebSocket."""

        if self._closed:
            raise ValueError("Browser is closed")
        self._pages = [page for page in self._pages if not page.closed]
        url = _with_token(self._base_url, self._token)
        transport = Transport(url, self._timeout, self._transport_factory)
        await transport.connect()
        if self._closed:
            await transport.close()
            raise ValueError("Browser is closed")
        page = Page(transport)
        self._pages.append(page)
        return page

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Open a page and close it when the context exits."""

        page = await self.new_page()
        try:
            yield page
        finally:
            await page.close()

    def get_pages(self) -> list[Page]:
        """Return pages whose transports remain open."""

        return [page for page in self._pages if not page.closed]

    async def close(self) -> None:
        """Close every page opened by this browser."""

        if self._closed:
            return
        self._closed = True
        results = await asyncio.gather(
            *(page.close() for page in self._pages if not page.closed),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to close a bap page",
                    exc_info=(type(result), result, result.__traceback__),
                )

    async def __aenter__(self) -> Browser:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()


def _with_token(url: str | None, token: str | None) -> str | None:
    if url is None or token is None:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("token", token))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
