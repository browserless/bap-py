"""Snapshot-backed element handle with live page actions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Unpack
from urllib.parse import quote

from .errors import BAPValueError
from .types.options import ClickOptions, QuerySelectorOptions, TypeOptions
from .types.responses import ClickResponse, HoverResponse, SelectResponse, TypeResponse

if TYPE_CHECKING:
    from .page import Page


# BrowserQL pastes selectors into JavaScript escaping only double quotes.
# URI-encoded JSON survives that extra string parse, including nested selectors.
# JSON escapes lone UTF-16 surrogates before URI encoding can reject them.
def _selector_literal(selector: str) -> str:
    encoded = quote(json.dumps(selector), safe="!~*'()")
    return f"JSON.parse(decodeURIComponent({json.dumps(encoded)}))"


def _selector_expression(selector: str, *, all_matches: bool = False) -> str:
    method = "querySelectorAll" if all_matches else "querySelector"
    quoted = _selector_literal(selector)
    return (
        f"(() => {{ try {{ return document.{method}({quoted}); }} "
        f"catch {{ return eval({quoted}); }} }})()"
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
        """Element HTML. Requires html=True on the query that produced this handle."""
        return self._optional_html("innerHTML", "inner_html")

    def _optional_html(self, key: str, attribute: str) -> str | None:
        if key not in self._properties:
            raise BAPValueError(
                f"{attribute} was not requested; pass html=True to the query "
                "that produced this handle"
            )
        return self._properties.get(key)

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
        """Element markup. Requires html=True on the query that produced this handle."""
        return self._optional_html("outerHTML", "outer_html")

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

    async def query_selector(
        self, selector: str, **options: Unpack[QuerySelectorOptions]
    ) -> ElementHandle | None:
        return await self._page.query_selector(
            f"{_selector_expression(self._selector)}?.querySelector({_selector_literal(selector)})",
            **options,
        )

    async def query_selector_all(
        self, selector: str, **options: Unpack[QuerySelectorOptions]
    ) -> list[ElementHandle]:
        return await self._page.query_selector_all(
            f"{_selector_expression(self._selector)}"
            f"?.querySelectorAll({_selector_literal(selector)}) ?? []",
            **options,
        )
