from __future__ import annotations

import threading
from collections.abc import Mapping

import browserless_bap.sync_api as sync_bap

from ._server import ServerThread


def test_sync_event_callback_can_call_page_without_deadlocking() -> None:
    with ServerThread() as server:
        with sync_bap.Browserless.connect(
            browser_ws_endpoint=server.url,
            timeout=2_000,
        ) as browser:
            with browser.page() as page:
                done = threading.Event()
                values: list[str] = []

                def callback(message: object) -> None:
                    assert isinstance(message, Mapping)
                    values.append(str(message["text"]))
                    values.append(page.title())
                    values.append(threading.current_thread().name)
                    done.set()

                assert page.listener_count("console") == 0
                page.on("console", callback)
                assert page.listener_count("console") == 1
                assert done.wait(timeout=2)
                page.off("console", callback)
                assert page.listener_count("console") == 0

                assert values == ["hello", "Mock Title", "bap-sync-events"]
                assert server.subscribe_count == 2
