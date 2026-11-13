from __future__ import annotations

import asyncio
import gc
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any, cast

import pytest

import browserless_bap.sync_api.page as page_module
from browserless_bap._unset import UNSET
from browserless_bap.element_handle import ElementHandle as AsyncElementHandle
from browserless_bap.errors import BAPValueError
from browserless_bap.sync_api._bridge import LoopThread
from browserless_bap.sync_api.browser import Browser
from browserless_bap.sync_api.element_handle import ElementHandle
from browserless_bap.sync_api.page import Page


class AsyncPage:
    def __init__(self) -> None:
        self.closed = False
        self.listeners: dict[str, list[Callable[[object], object]]] = {}
        self.thread_names: list[str] = []
        self.query_options: list[dict[str, object]] = []

    async def goto(self, url: str, **options: object) -> dict[str, object]:
        self.thread_names.append(threading.current_thread().name)
        return {"url": url, **options}

    async def title(self) -> str:
        return "Example Domain"

    async def query_selector(
        self, selector: str, **options: object
    ) -> AsyncElementHandle:
        self.query_options.append(options)
        return AsyncElementHandle(
            cast(Any, self),
            selector,
            {
                "innerHTML": "<span>child</span>",
                "innerText": "child",
                "id": "child",
                "className": "item",
                "localName": "span",
                "outerHTML": '<span id="child">child</span>',
                "childElementCount": 0,
            },
        )

    async def query_selector_all(
        self, selector: str, **options: object
    ) -> list[AsyncElementHandle]:
        return [await self.query_selector(selector, **options)]

    async def eval_on_selector(self, selector: str) -> str:
        return "current child"

    def on(self, event: str, callback: Callable[[object], object]) -> AsyncPage:
        self.listeners.setdefault(event, []).append(callback)
        return self

    def once(self, event: str, callback: Callable[[object], object]) -> AsyncPage:
        return self.on(event, callback)

    def off(self, event: str, callback: Callable[[object], object]) -> AsyncPage:
        listeners = self.listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)
        return self

    def remove_all_listeners(self, event: str | None = None) -> AsyncPage:
        if event is None:
            self.listeners.clear()
        else:
            self.listeners.pop(event, None)
        return self

    def emit(self, event: str, payload: object) -> bool:
        listeners = list(self.listeners.get(event, ()))
        for callback in listeners:
            callback(payload)
        return bool(listeners)

    async def fire(self, event: str, payload: object) -> None:
        for callback in list(self.listeners.get(event, [])):
            result = callback(payload)
            if asyncio.iscoroutine(result):
                await result

    async def close(self) -> None:
        self.closed = True


class AsyncBrowser:
    def __init__(self) -> None:
        self.created: list[AsyncPage] = []

    async def new_page(self) -> AsyncPage:
        page = AsyncPage()
        self.created.append(page)
        return page

    def get_pages(self) -> list[AsyncPage]:
        return [page for page in self.created if not page.closed]

    async def close(self) -> None:
        await asyncio.gather(*(page.close() for page in self.created))


def test_page_calls_run_on_bridge_and_wrap_handles() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    try:
        assert page.goto("https://example.com", timeout=10) == {
            "url": "https://example.com",
            "timeout": 10,
            "wait_until": UNSET,
            "wait_until_all": UNSET,
            "referer": UNSET,
            "referrer_policy": UNSET,
            "remote_response_metadata": UNSET,
        }
        assert impl.thread_names == ["bap-sync-loop"]
        handle = page.query_selector("#child")
        assert isinstance(handle, ElementHandle)
        assert handle.inner_text == "child"
        assert handle.text_content() == "current child"
        assert isinstance(handle.query_selector("span"), ElementHandle)
        assert len(handle.query_selector_all("span")) == 1
        handle.query_selector("span", timeout=5, visible=False, html=True)
        assert impl.query_options[-1] == {"timeout": 5, "visible": False, "html": True}
        handle.query_selector_all("span", timeout=10, visible=True, html=True)
        assert impl.query_options[-1] == {"timeout": 10, "visible": True, "html": True}
        assert len(page.query_selector_all(".item")) == 1
        plain = ElementHandle(AsyncElementHandle(cast(Any, impl), "p", {}), bridge)
        for attribute in ("inner_html", "outer_html"):
            with pytest.raises(BAPValueError, match="html=True"):
                getattr(plain, attribute)
    finally:
        bridge.close()


def test_sync_callback_can_make_sync_page_call_without_deadlock() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    done = threading.Event()
    values: list[str] = []

    def callback(payload: object) -> None:
        response = page.goto("https://example.com")
        assert response is not None
        values.append(str(payload))
        values.append(str(response["url"]))
        values.append(threading.current_thread().name)
        done.set()

    try:
        page.on("console", callback)
        bridge.run(impl.fire("console", "hello"))
        assert done.wait(timeout=2)
        assert values == [
            "hello",
            "https://example.com",
            "bap-sync-events",
        ]
    finally:
        bridge.close()


def test_callback_error_routes_through_page_error_event() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    done = threading.Event()
    errors: list[str] = []

    def fail(_payload: object) -> None:
        raise ValueError("callback failed")

    def on_error(error: object) -> None:
        errors.append(str(error))
        done.set()

    try:
        page.on("error", on_error)
        page.on("console", fail)
        bridge.run(impl.fire("console", "hello"))
        assert done.wait(timeout=2)
        assert errors == ["callback failed"]
    finally:
        bridge.close()


def test_sync_once_releases_wrapper_and_can_be_cancelled() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    delivered: list[str] = []
    drained = threading.Event()

    def callback(payload: object) -> None:
        delivered.append(str(payload))

    def cancelled(_payload: object) -> None:
        delivered.append("cancelled")

    try:
        page.once("console", callback)
        assert ("console", callback, True) in page._event_wrappers
        bridge.run(impl.fire("console", "first"))
        bridge.run(impl.fire("console", "second"))
        assert page._dispatcher is not None
        page._dispatcher.submit(drained.set)
        assert drained.wait(timeout=2)
        assert delivered == ["first"]
        assert ("console", callback, True) not in page._event_wrappers

        page.once("console", cancelled)
        page.off("console", cancelled)
        bridge.run(impl.fire("console", "ignored"))
        drained.clear()
        page._dispatcher.submit(drained.set)
        assert drained.wait(timeout=2)
        assert delivered == ["first"]
        assert ("console", cancelled, True) not in page._event_wrappers
    finally:
        bridge.close()


@pytest.mark.parametrize("registration_order", [("on", "once"), ("once", "on")])
def test_on_and_once_keep_distinct_wrappers(
    registration_order: tuple[str, str],
) -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    delivered: list[str] = []
    drained = threading.Event()

    def callback(payload: object) -> None:
        delivered.append(str(payload))

    try:
        for method_name in registration_order:
            getattr(page, method_name)("console", callback)

        assert ("console", callback, False) in page._event_wrappers
        assert ("console", callback, True) in page._event_wrappers
        bridge.run(impl.fire("console", "first"))
        bridge.run(impl.fire("console", "second"))
        assert page._dispatcher is not None
        page._dispatcher.submit(drained.set)

        assert drained.wait(timeout=2)
        assert delivered.count("first") == 2
        assert delivered.count("second") == 1
        assert ("console", callback, False) in page._event_wrappers
        assert ("console", callback, True) not in page._event_wrappers

        page.on("dialog", callback)
        page.once("dialog", callback)
        page.off("dialog", callback)
        assert not [
            key for key in page._event_wrappers if key[:2] == ("dialog", callback)
        ]
        assert impl.listeners["dialog"] == []
    finally:
        bridge.close()


def test_subscription_start_wait_is_bounded_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = LoopThread()

    class NeverStartsPage(AsyncPage):
        async def _wait_subscription_started(self, _event: str) -> None:
            await asyncio.Event().wait()

    impl = NeverStartsPage()
    page = Page(impl, bridge)
    monkeypatch.setattr(page_module, "_SUBSCRIPTION_START_TIMEOUT", 0.01)
    try:
        assert page.on("console", lambda _payload: None) is page
    finally:
        bridge.close()


def test_subscription_start_failure_is_best_effort() -> None:
    bridge = LoopThread()

    class FailingStartPage(AsyncPage):
        async def _wait_subscription_started(self, _event: str) -> None:
            raise RuntimeError("subscription failed")

    page = Page(FailingStartPage(), bridge)
    try:
        assert page.on("console", lambda _payload: None) is page
    finally:
        bridge.close()


def test_off_tolerates_once_wrapper_removed_concurrently() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)

    class RacingWrappers(
        dict[
            tuple[str, Callable[[object], object], bool],
            Callable[[object], object],
        ]
    ):
        def pop(
            self,
            key: Any,
            default: Any = None,
        ) -> Any:
            super().pop(key, None)
            return super().pop(key, default)

    def callback(_payload: object) -> None:
        return None

    try:
        page.once("console", callback)
        page._event_wrappers = RacingWrappers(page._event_wrappers)

        assert page.off("console", callback) is page
    finally:
        bridge.close()


def test_on_blocks_until_subscription_start_attempt_finishes() -> None:
    bridge = LoopThread()

    class WaitablePage(AsyncPage):
        def __init__(self) -> None:
            super().__init__()
            self.ready: asyncio.Event | None = None
            self.waited = False

        def on(self, event: str, callback: Callable[[object], object]) -> AsyncPage:
            result = super().on(event, callback)
            self.ready = asyncio.Event()
            asyncio.get_running_loop().call_soon(self.ready.set)
            return result

        async def _wait_subscription_started(self, _event: str) -> None:
            assert self.ready is not None
            await self.ready.wait()
            self.waited = True

    impl = WaitablePage()
    page = Page(impl, bridge)
    try:
        page.on("console", lambda _payload: None)
        assert impl.waited
    finally:
        bridge.close()


def test_browser_context_manager_closes_pages() -> None:
    bridge = LoopThread()
    impl = AsyncBrowser()
    try:
        with Browser(impl, bridge) as browser:
            with browser.page() as page:
                assert not page.closed
            assert page.closed
        assert browser.get_pages() == []
    finally:
        bridge.close()


def test_slow_callback_on_one_page_does_not_delay_another() -> None:
    bridge = LoopThread()
    impl_a, impl_b = AsyncPage(), AsyncPage()
    page_a, page_b = Page(impl_a, bridge), Page(impl_b, bridge)
    started, release, delivered = (threading.Event() for _ in range(3))
    threads: list[threading.Thread] = []

    def slow(_payload: object) -> None:
        threads.append(threading.current_thread())
        started.set()
        release.wait(timeout=5)

    def fast(_payload: object) -> None:
        threads.append(threading.current_thread())
        delivered.set()

    try:
        page_a.on("console", slow)
        page_b.on("console", fast)
        bridge.run(impl_a.fire("console", "a"))
        assert started.wait(timeout=2)
        bridge.run(impl_b.fire("console", "b"))
        assert delivered.wait(timeout=1)
        assert threads[0] is not threads[1]
    finally:
        release.set()
        bridge.close()


def test_once_survives_full_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_module, "_CALLBACK_QUEUE_SIZE", 1, raising=False)
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    started, release, drained = (threading.Event() for _ in range(3))
    delivered: list[str] = []

    def callback(payload: object) -> None:
        delivered.append(str(payload))

    def block() -> None:
        started.set()
        release.wait(timeout=5)

    try:
        page.once("console", callback)
        dispatcher = page._dispatcher
        assert dispatcher is not None
        assert dispatcher.submit(block)
        assert started.wait(timeout=2)
        assert dispatcher.submit(lambda: None)
        bridge.run(impl.fire("console", "first"))
        assert ("console", callback, True) in page._event_wrappers
        assert len(impl.listeners["console"]) == 1
        release.set()
        dispatcher._queue.join()
        bridge.run(impl.fire("console", "second"))
        dispatcher._queue.join()
        bridge.run(impl.fire("console", "third"))
        assert dispatcher.submit(drained.set)
        assert drained.wait(timeout=2)
        assert delivered == ["second"]
    finally:
        release.set()
        bridge.close()


def test_get_pages_returns_same_page_and_off_works_through_it() -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)
    try:
        page = browser.new_page()

        def callback(_payload: object) -> None:
            pass

        page.on("console", callback)
        assert browser.get_pages()[0] is page
        assert browser.pages()[0] is page
        browser.get_pages()[0].off("console", callback)
        assert page._impl.listeners["console"] == []
        page.close()
        assert browser.get_pages() == []
    finally:
        browser.close()
        bridge.close()


def test_get_pages_preserves_page_created_after_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)
    snapshot, resume = threading.Event(), threading.Event()
    invoke = browser._invoke
    listings: list[list[Page]] = []

    def paused_invoke(method: str, *args: object, **kwargs: object) -> Any:
        result = invoke(method, *args, **kwargs)
        if method == "get_pages" and not snapshot.is_set():
            snapshot.set()
            assert resume.wait(timeout=2)
        return result

    monkeypatch.setattr(browser, "_invoke", paused_invoke)
    reader = threading.Thread(target=lambda: listings.append(browser.get_pages()))
    try:
        reader.start()
        assert snapshot.wait(timeout=2)
        page = browser.new_page()
        page.on("console", callback := lambda _payload: None)
        resume.set()
        reader.join(timeout=2)
        assert not reader.is_alive()
        assert listings == [[]]
        assert browser.get_pages() == [page]
        browser.get_pages()[0].off("console", callback)
        assert page._impl.listeners["console"] == []
        dispatcher = page._dispatcher
        assert dispatcher is not None
        browser.close()
        dispatcher._thread.join(timeout=2)
        assert not dispatcher._thread.is_alive()
    finally:
        resume.set()
        reader.join(timeout=2)
        browser.close()
        bridge.close()


@pytest.mark.parametrize("close_error", [False, True])
def test_page_context_releases_closed_wrapper(
    close_error: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)

    def close() -> None:
        if close_error:
            raise ValueError("close failed")

    try:
        try:
            with browser.page() as page:
                reference = weakref.ref(page)
                monkeypatch.setattr(page, "close", close)
        except ValueError:
            assert close_error
        monkeypatch.undo()
        del page
        gc.collect()
        assert reference() is None
    finally:
        browser.close()
        bridge.close()


def test_off_waits_for_once_dispatch_instead_of_racing() -> None:
    bridge = LoopThread()
    impl = AsyncPage()
    page = Page(impl, bridge)
    delivered: list[object] = []
    helpers: list[threading.Thread] = []

    class RacingWrappers(
        dict[tuple[str, Callable[[object], object], bool], Callable[[object], object]]
    ):
        raced = False

        def __iter__(self) -> Iterator[tuple[str, Callable[[object], object], bool]]:
            iterator = super().__iter__()
            if not self.raced:
                self.raced = True
                first = next(iterator)
                helper = threading.Thread(
                    target=lambda: bridge.run(impl.fire("console", "x"))
                )
                helpers.append(helper)
                helper.start()
                helper.join(timeout=0.5)
                yield first
            yield from iterator

    try:
        page.once("console", delivered.append)
        page._event_wrappers = RacingWrappers(page._event_wrappers)
        page.off("console", lambda _payload: None)
        for helper in helpers:
            helper.join(timeout=2)
            assert not helper.is_alive()
        dispatcher = page._dispatcher
        assert dispatcher is not None
        dispatcher._queue.join()
        assert delivered == ["x"]
    finally:
        bridge.close()


def test_new_page_prunes_closed_wrappers() -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)
    references: list[weakref.ReferenceType[Page]] = []
    try:
        for _ in range(5):
            page = browser.new_page()
            references.append(weakref.ref(page))
            page.close()
        del page
        current = browser.new_page()
        gc.collect()
        assert len(browser._pages) == 1
        assert all(reference() is None for reference in references)
        assert browser.get_pages() == [current]
    finally:
        browser.close()
        bridge.close()


@pytest.mark.parametrize("close_owner", ["browser", "bridge"])
def test_close_shares_callback_worker_deadline(close_owner: str) -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)
    bridge.track_browser(browser._impl)
    release = threading.Event()
    started = [threading.Event() for _ in range(4)]
    workers: list[threading.Thread] = []

    def busy(ready: threading.Event, _payload: object) -> None:
        workers.append(threading.current_thread())
        ready.set()
        release.wait(timeout=15)

    try:
        for ready in started:
            page = browser.new_page()
            page.on("console", partial(busy, ready))
            page.emit("console", "busy")
        assert all(ready.wait(timeout=2) for ready in started)
        before = time.monotonic()
        {"browser": browser.close, "bridge": bridge.close}[close_owner]()
        elapsed = time.monotonic() - before
        assert elapsed < 3, f"closing four busy pages took {elapsed:.2f}s"
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()
        if close_owner == "browser":
            browser.close()
        bridge.close()


@pytest.mark.parametrize("close_owner", ["page", "browser", "bridge", "implementation"])
def test_close_stops_page_dispatcher(close_owner: str) -> None:
    bridge = LoopThread()
    browser = Browser(AsyncBrowser(), bridge)
    page = browser.new_page()
    try:
        page.on("console", lambda _payload: None)
        dispatcher = page._dispatcher
        assert dispatcher is not None
        close = {"page": page.close, "browser": browser.close, "bridge": bridge.close}
        if close_owner == "implementation":
            bridge.run(page._impl.close())
            assert browser.get_pages() == []
        else:
            close[close_owner]()
        dispatcher._thread.join(timeout=2)
        assert not dispatcher._thread.is_alive()
        if close_owner == "page":
            assert page._dispatcher is None
    finally:
        bridge.close()
