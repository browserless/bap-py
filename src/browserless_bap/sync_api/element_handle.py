"""Synchronous element handle."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Unpack, cast

from ..types.options import ClickOptions, TypeOptions
from ..types.responses import ClickResponse, HoverResponse, SelectResponse, TypeResponse
from ._base import SyncBase


class ElementHandle(SyncBase[Any]):
    @property
    def inner_html(self) -> str | None:
        return cast(str | None, self._impl.inner_html)

    @property
    def inner_text(self) -> str | None:
        return cast(str | None, self._impl.inner_text)

    @property
    def id(self) -> str | None:
        return cast(str | None, self._impl.id)

    @property
    def class_name(self) -> str | None:
        return cast(str | None, self._impl.class_name)

    @property
    def local_name(self) -> str | None:
        return cast(str | None, self._impl.local_name)

    @property
    def outer_html(self) -> str | None:
        return cast(str | None, self._impl.outer_html)

    @property
    def child_element_count(self) -> int | None:
        return cast(int | None, self._impl.child_element_count)

    @property
    def selector(self) -> str:
        return cast(str, self._impl.selector)

    def click(self, **options: Unpack[ClickOptions]) -> ClickResponse:
        return cast(ClickResponse, self._invoke("click", **options))

    def hover(self) -> HoverResponse:
        return cast(HoverResponse, self._invoke("hover"))

    def type(self, text: str, **options: Unpack[TypeOptions]) -> TypeResponse:
        return cast(TypeResponse, self._invoke("type", text, **options))

    def select_option(self, value: str | Sequence[str]) -> SelectResponse:
        return cast(SelectResponse, self._invoke("select_option", value))

    def screenshot(self, *, path: str | None = None) -> bytes:
        return cast(bytes, self._invoke("screenshot", path=path))

    def text_content(self) -> str:
        return cast(str, self._invoke("text_content"))

    def query_selector(self, selector: str) -> ElementHandle | None:
        value = self._invoke("query_selector", selector)
        return None if value is None else ElementHandle(value, self._bridge)

    def query_selector_all(self, selector: str) -> list[ElementHandle]:
        values = cast(list[object], self._invoke("query_selector_all", selector))
        return [ElementHandle(value, self._bridge) for value in values]
