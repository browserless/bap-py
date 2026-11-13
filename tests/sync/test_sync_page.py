from __future__ import annotations

import socket
import time
from typing import Any, cast

import pytest

import browserless_bap.sync_api as sync_bap
from browserless_bap.errors import TimeoutError as BAPTimeoutError

from ._server import ServerThread


@pytest.mark.timeout(3)
def test_sync_operation_timeout_raises() -> None:
    browserless = cast(Any, sync_bap.Browserless)
    with ServerThread(reply=False) as server:
        with browserless.connect(browser_ws_endpoint=server.url) as browser:
            with browser.page() as page:
                started = time.monotonic()
                with pytest.raises(BAPTimeoutError) as caught:
                    page.send("query { neverAnswered }", timeout=100)
                assert caught.value.timeout_ms == 100
                assert time.monotonic() - started < 2


@pytest.mark.timeout(3)
def test_sync_connect_timeout_raises() -> None:
    browserless = cast(Any, sync_bap.Browserless)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with browserless.connect(
            browser_ws_endpoint=f"ws://127.0.0.1:{listener.getsockname()[1]}/bql",
            connect_timeout=100,
        ) as browser:
            started = time.monotonic()
            with pytest.raises(BAPTimeoutError) as caught:
                browser.new_page()
            assert caught.value.operation == "connect"
            assert caught.value.timeout_ms == 100
            assert time.monotonic() - started < 2


def test_sync_page_uses_a_server_on_an_independent_loop_thread() -> None:
    browserless = cast(Any, sync_bap.Browserless)
    with ServerThread() as server:
        with browserless.connect(
            browser_ws_endpoint=server.url,
            timeout=2_000,
        ) as browser:
            with browser.page() as page:
                response = page.goto("https://example.com")
                assert response is not None
                assert response["status"] == 200
                assert page.title() == "Mock Title"

        assert server.thread_name == "bap-test-server"
        assert server.subscribe_count == 2


def test_sync_live_url_wait_retains_early_completion() -> None:
    browserless = cast(Any, sync_bap.Browserless)
    with ServerThread() as server:
        with browserless.connect(
            browser_ws_endpoint=server.url, timeout=2_000
        ) as browser:
            with browser.page() as page:
                link = page.live_url(instructions="Sign in")
                assert page.wait_for_live_complete()["reason"] == "userDone"
                assert page.close_live_url(link["liveURLId"]) == {"liveURLId": "link"}


def test_sync_live_url_accepts_rich_instructions() -> None:
    browserless = cast(Any, sync_bap.Browserless)
    with ServerThread() as server:
        with browserless.connect(
            browser_ws_endpoint=server.url, timeout=2_000
        ) as browser:
            with browser.page() as page:
                assert page.live_url(
                    instructions={
                        "layout": "panel",
                        "format": "markdown",
                        "title": "Login",
                        "summary": "**Sign in**",
                        "steps": ["Open inbox", "Enter code"],
                        "currentStep": 2,
                    },
                    done_label="Continue",
                ) == {"liveURLId": "link", "liveURL": "https://example.com/live"}
                assert server.live_url_variables == {
                    "instructions": {
                        "layout": "panel",
                        "format": "markdown",
                        "title": "Login",
                        "summary": "**Sign in**",
                        "steps": ["Open inbox", "Enter code"],
                        "currentStep": 2,
                    },
                    "doneLabel": "Continue",
                }
