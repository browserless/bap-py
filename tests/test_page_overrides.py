# Remote-operation timeout parameters are part of the public contract.
# ruff: noqa: ASYNC109

import inspect
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, assert_type, cast

import pytest

from browserless_bap._page_generated import PageGenerated
from browserless_bap._unset import UnsetType
from browserless_bap.element_handle import _selector_expression, _selector_literal
from browserless_bap.page import Page
from browserless_bap.transport import (
    MessageListener,
    Subscriber,
    Transport,
    Unsubscribe,
)
from browserless_bap.types.responses import (
    ClickResponse,
    HTTPResponse,
    ResponseResponse,
    SelectResponse,
)

if TYPE_CHECKING:
    from browserless_bap.element_handle import ElementHandle
    from browserless_bap.sync_api.element_handle import (
        ElementHandle as SyncElementHandle,
    )
    from browserless_bap.sync_api.page import Page as SyncPage

    async def _assert_public_type_contract(
        page: Page,
        element: ElementHandle,
        sync_page: SyncPage,
        sync_element: SyncElementHandle,
    ) -> None:
        assert_type(await page.goto("https://example.com"), HTTPResponse | None)
        assert_type(await page.response(), list[ResponseResponse])
        assert_type(
            await page.select_option("select", "value"),
            SelectResponse,
        )
        assert_type(await element.click(), ClickResponse)
        assert_type(sync_page.goto("https://example.com"), HTTPResponse | None)
        assert_type(sync_page.response(), list[ResponseResponse])
        assert_type(sync_element.click(), ClickResponse)


class RecordingTransport:
    closed = False

    def on_message(self, _listener: MessageListener) -> Callable[[], None]:
        return lambda: None

    def operation_timeout(
        self,
        timeout: float | None,
        cushion: float = 0,
    ) -> float:
        resolved = 30_000 if timeout is None else timeout
        return resolved + cushion if resolved > 0 else resolved

    async def send(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("RecordingPage overrides _execute")

    async def subscribe(
        self,
        query: str,
        variables: Mapping[str, Any] | None,
        subscriber: Subscriber,
    ) -> Unsubscribe:
        async def unsubscribe() -> None:
            return None

        return unsubscribe

    async def close(self) -> None:
        self.closed = True


class RecordingPage(Page):
    def __init__(self) -> None:
        super().__init__(cast(Transport, RecordingTransport()))
        self.calls: list[
            tuple[
                str,
                Mapping[str, Any] | None,
                str,
                float | UnsetType | None,
            ]
        ] = []

    async def _execute(
        self,
        mutation_name: str,
        args: Mapping[str, Any] | None,
        response_type: str,
        *,
        timeout: float | UnsetType | None = None,
    ) -> Any:
        self.calls.append((mutation_name, args, response_type, timeout))
        if mutation_name == "evaluate":
            return {"value": "2"}
        if mutation_name == "response":
            return []
        return {"ok": True}


class NullResultPage(RecordingPage):
    async def _execute(
        self,
        mutation_name: str,
        args: Mapping[str, Any] | None,
        response_type: str,
        *,
        timeout: float | UnsetType | None = None,
    ) -> None:
        self.calls.append((mutation_name, args, response_type, timeout))
        return None


class SelectorListPage(RecordingPage):
    async def _execute(
        self,
        mutation_name: str,
        args: Mapping[str, Any] | None,
        response_type: str,
        *,
        timeout: float | UnsetType | None = None,
    ) -> Any:
        self.calls.append((mutation_name, args, response_type, timeout))
        if mutation_name == "querySelectorAll":
            return [{"innerText": "first"}, {"innerText": "second"}]
        return {"ok": True}


@pytest.mark.parametrize("method_name", ["goto", "response"])
def test_concrete_overrides_preserve_generated_parameters(
    method_name: str,
) -> None:
    generated = inspect.signature(getattr(PageGenerated, method_name))
    concrete = inspect.signature(getattr(Page, method_name))

    assert list(concrete.parameters) == list(generated.parameters)
    for name, parameter in generated.parameters.items():
        assert concrete.parameters[name].kind is parameter.kind
        assert concrete.parameters[name].default == parameter.default
        assert concrete.parameters[name].annotation == parameter.annotation
    assert concrete.return_annotation == generated.return_annotation


@pytest.mark.asyncio
async def test_goto_and_response_opt_ins_never_leak_client_flags() -> None:
    page = RecordingPage()
    await page.goto(
        "https://example.com",
        timeout=500,
        remote_response_metadata=True,
    )
    await page.response(body_encoding=True, timeout=750)

    goto = page.calls[0]
    assert goto[0] == "goto"
    assert goto[1] == {"url": "https://example.com", "timeout": 500}
    assert goto[2] == "HTTPResponseWithRemoteMetadata"
    assert goto[1] is not None
    assert "remoteResponseMetadata" not in goto[1]

    response = page.calls[1]
    assert response[2] == "ResponseResponseWithBodyEncoding"
    assert response[1] is not None
    assert "bodyEncoding" not in response[1]
    await page.close()


@pytest.mark.asyncio
async def test_tag_paths_read_content_and_sanitize_source_url(
    tmp_path: Path,
) -> None:
    script = tmp_path / "bad\nname.js"
    script.write_text("globalThis.ok = true;", encoding="utf-8")
    style = tmp_path / "bad*/name.css"
    style.parent.mkdir(parents=True, exist_ok=True)
    style.write_text("body { color: red; }", encoding="utf-8")
    page = RecordingPage()

    await page.add_script_tag(path=script)
    await page.add_style_tag(path=style)

    script_args = page.calls[0][1]
    assert script_args is not None
    assert "\nname.js" not in script_args["content"]
    assert "sourceURL=" in script_args["content"]
    style_args = page.calls[1][1]
    assert style_args is not None
    assert "*/name.css" not in style_args["content"]
    await page.close()


@pytest.mark.asyncio
async def test_empty_inline_tag_content_is_an_explicit_source() -> None:
    page = RecordingPage()

    await page.add_script_tag(content="")
    await page.add_style_tag(content="")

    assert page.calls[0][1] is not None
    assert page.calls[0][1]["content"] == ""
    assert page.calls[1][1] is not None
    assert page.calls[1][1]["content"] == ""
    await page.close()


@pytest.mark.asyncio
async def test_wait_for_function_rewrite_preserves_raw_timeout() -> None:
    page = RecordingPage()
    await page.wait_for_function(
        "async () => await fetch('/')",
        timeout=500,
        complete_on_promise_resolution=True,
    )

    _, args, _, timeout = page.calls[0]
    assert args is not None
    assert args["fn"].startswith("async () => { await (")
    assert "completeOnPromiseResolution" not in args
    assert timeout == 500
    await page.close()


@pytest.mark.asyncio
async def test_wait_for_function_awaits_plain_promise_factory() -> None:
    page = RecordingPage()
    await page.wait_for_function(
        "() => fetch('/')",
        complete_on_promise_resolution=True,
    )

    args = page.calls[0][1]
    assert args is not None
    assert args["fn"] == ("async () => { await (() => fetch('/'))(); return true; }")
    await page.close()


@pytest.mark.asyncio
async def test_query_selector_all_handles_ignore_nonmatching_siblings() -> None:
    page = SelectorListPage()

    handles = await page.query_selector_all(".item")
    await handles[0].click()
    await handles[1].click()

    expression = _selector_expression(".item", all_matches=True)
    assert handles[0].selector == f"({expression})[0]"
    assert handles[1].selector == f"({expression})[1]"
    assert page.calls[1][1] == {"selector": handles[0].selector}
    assert page.calls[2][1] == {"selector": handles[1].selector}
    await page.close()


@pytest.mark.asyncio
async def test_element_handle_descendant_selector_scopes_every_alternative() -> None:
    page = SelectorListPage()
    handle = (await page.query_selector_all(".item"))[0]

    await handle.query_selector("button, a")

    args = page.calls[1][1]
    assert args is not None
    scoped = cast(str, args["selector"])
    assert scoped == (
        f"{_selector_expression(handle.selector)}"
        f"?.querySelector({_selector_literal('button, a')})"
    )
    assert ".item button, a" not in scoped
    await page.close()


@pytest.mark.asyncio
async def test_element_handle_queries_forward_options() -> None:
    page = SelectorListPage()
    handle = (await page.query_selector_all(".item"))[0]
    await handle.query_selector("li", timeout=5000, visible=True)
    await handle.query_selector_all("li", timeout=750, visible=False)

    assert page.calls[2][1] is not None
    assert page.calls[2][1]["selector"] == (
        f"{_selector_expression(handle.selector)}"
        f"?.querySelectorAll({_selector_literal('li')}) ?? []"
    )
    for call, timeout, visible in zip(
        page.calls[1:], [5000, 750], [True, False], strict=True
    ):
        assert call[1] is not None
        assert call[1]["timeout"] == timeout
        assert call[1]["visible"] is visible
        assert call[3] == timeout
    await page.close()


@pytest.mark.asyncio
async def test_query_selector_all_encodes_once_and_skips_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import browserless_bap.element_handle as module

    calls: list[str] = []

    def encode(selector: str, *, all_matches: bool = False) -> str:
        calls.append(selector)
        return _selector_expression(selector, all_matches=all_matches)

    monkeypatch.setattr(module, "_selector_expression", encode)
    page = SelectorListPage()
    empty_page = NullResultPage()
    assert await empty_page.query_selector_all(".absent") == []
    assert calls == []
    assert len(await page.query_selector_all(".item")) == 2
    assert calls == [".item"]
    await empty_page.close()
    await page.close()


@pytest.mark.asyncio
async def test_evaluate_is_string_only_and_unwraps_value() -> None:
    page = RecordingPage()
    assert await page.evaluate("1 + 1") == "2"
    assert page.calls[0][1] == {"content": "1 + 1"}
    await page.close()


@pytest.mark.asyncio
async def test_generated_methods_preserve_defaults_for_null_results() -> None:
    page = NullResultPage()

    assert await page.title() == ""
    assert await page.cookies() == []
    assert await page.screenshot() == b""

    await page.close()
