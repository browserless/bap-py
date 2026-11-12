"""Snapshot-backed element handle with live page actions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Unpack

from .types.options import ClickOptions, TypeOptions
from .types.responses import ClickResponse, HoverResponse, SelectResponse, TypeResponse

if TYPE_CHECKING:
    from .page import Page


def _resolve_selector(selector: str, *, all_matches: bool = False) -> str:
    method = "querySelectorAll" if all_matches else "querySelector"
    fallback = "[]" if all_matches else "null"
    encoded = json.dumps(selector)
    return (
        "(() => { try { return document."
        f"{method}({encoded}); "
        f"}} catch {{ return eval({encoded}) ?? {fallback}; }} }})()"
    )


def _selector_at(selector: str, index: int) -> str:
    resolved = _resolve_selector(selector, all_matches=True)
    return f"({resolved})[{index}] ?? null"


def _scoped_selector(parent: str, selector: str, *, all_matches: bool = False) -> str:
    resolved_parent = _resolve_selector(parent)
    method = "querySelectorAll" if all_matches else "querySelector"
    fallback = "[]" if all_matches else "null"
    encoded = json.dumps(selector)
    return (
        "(() => { "
        f"const root = {resolved_parent}; "
        f"if (!root) return {fallback}; "
        f"return root.{method}({encoded}); "
        "})()"
    )


class ElementHandle:
    """A matched element's properties plus selector-scoped actions."""

    def __init__(
        self,
        page: Page,
        selector: str,
        properties: Mapping[str, Any],
    ) -> None:
        self._page = page
        self._selector = selector
        self._properties = properties

    @property
    def inner_html(self) -> str | None:
        return self._properties.get("innerHTML")

    @property
    def inner_text(self) -> str | None:
        return self._properties.get("innerText")

    @property
    def id(self) -> str | None:
        return self._properties.get("id")

    @property
    def class_name(self) -> str | None:
        return self._properties.get("className")

    @property
    def local_name(self) -> str | None:
        return self._properties.get("localName")

    @property
    def outer_html(self) -> str | None:
        return self._properties.get("outerHTML")

    @property
    def child_element_count(self) -> int | None:
        return self._properties.get("childElementCount")

    @property
    def selector(self) -> str:
        return self._selector

    async def click(self, **options: Unpack[ClickOptions]) -> ClickResponse:
        return await self._page.click(self._selector, **options)

    async def hover(self) -> HoverResponse:
        return await self._page.hover(self._selector)

    async def type(self, text: str, **options: Unpack[TypeOptions]) -> TypeResponse:
        return await self._page.type(self._selector, text, **options)

    async def select_option(self, value: str | Sequence[str]) -> SelectResponse:
        return await self._page.select_option(self._selector, value)

    async def screenshot(self, *, path: str | None = None) -> bytes:
        options: dict[str, Any] = {"selector": self._selector}
        if path is not None:
            options["path"] = path
        return await self._page.screenshot(**options)

    async def text_content(self) -> str:
        return await self._page.eval_on_selector(self._selector)

    async def query_selector(self, selector: str) -> ElementHandle | None:
        return await self._page.query_selector(
            _scoped_selector(self._selector, selector)
        )

    async def query_selector_all(self, selector: str) -> list[ElementHandle]:
        return await self._page.query_selector_all(
            _scoped_selector(self._selector, selector, all_matches=True)
        )
