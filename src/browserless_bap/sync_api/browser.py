"""Synchronous Browser facade."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self

from ._base import SyncBase
from .page import Page


class Browser(SyncBase[Any]):
    def new_page(self) -> Page:
        return Page(self._invoke("new_page"), self._bridge)

    def get_pages(self) -> list[Page]:
        return [Page(page, self._bridge) for page in self._invoke("get_pages")]

    def pages(self) -> list[Page]:
        return self.get_pages()

    @contextmanager
    def page(self) -> Iterator[Page]:
        """Open a page and close it when the context exits."""

        page = self.new_page()
        try:
            yield page
        finally:
            page.close()

    def close(self) -> None:
        try:
            self._invoke("close")
        finally:
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
