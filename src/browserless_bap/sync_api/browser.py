"""Synchronous Browser facade."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any, Self

from ._base import SyncBase
from ._bridge import LoopThread
from .page import Page


class Browser(SyncBase[Any]):
    def __init__(self, impl: Any, bridge: LoopThread | None = None) -> None:
        super().__init__(impl, bridge)
        self._pages: dict[int, Page] = {}
        self._pages_lock = Lock()

    def _wrap_page(self, impl: Any) -> Page:
        with self._pages_lock:
            page = self._pages.get(id(impl))
            if page is None or page._impl is not impl:
                page = self._pages[id(impl)] = Page(impl, self._bridge)
            return page

    def new_page(self) -> Page:
        return self._wrap_page(self._invoke("new_page"))

    def get_pages(self) -> list[Page]:
        with self._pages_lock:
            self._pages = {
                key: page for key, page in self._pages.items() if not page.closed
            }
        impls = self._invoke("get_pages")
        return [self._wrap_page(impl) for impl in impls]

    def pages(self) -> list[Page]:
        return self.get_pages()

    @contextmanager
    def page(self) -> Iterator[Page]:
        """Open a page and close it when the context exits."""

        page = self.new_page()
        try:
            yield page
        finally:
            try:
                page.close()
            finally:
                with self._pages_lock:
                    if self._pages.get(id(page._impl)) is page:
                        del self._pages[id(page._impl)]

    def close(self) -> None:
        try:
            self._invoke("close")
        finally:
            with self._pages_lock:
                pages = list(self._pages.values())
                self._pages.clear()
            for page in pages:
                page._close_dispatcher()
            self._bridge.untrack_browser(self._impl)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()
