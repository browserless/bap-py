from __future__ import annotations

import asyncio
import concurrent.futures as cf
import inspect
import threading
import time

import pytest

import browserless_bap.sync_api._bridge as bridge_module
from browserless_bap.sync_api._bridge import CallbackDispatcher, LoopThread


async def _value(value: int) -> int:
    await asyncio.sleep(0)
    return value


def test_run_returns_async_result() -> None:
    bridge = LoopThread()
    try:
        assert bridge.run(_value(42)) == 42
    finally:
        bridge.close()


def test_run_rejects_active_asyncio_loop_without_leaking_coroutine() -> None:
    bridge = LoopThread()

    async def caller() -> str:
        coroutine = _value(1)
        with pytest.raises(RuntimeError, match=r"browserless_bap\.async_api"):
            bridge.run(coroutine)
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
        return "ok"

    try:
        assert asyncio.run(caller()) == "ok"
    finally:
        bridge.close()


def test_run_rejects_bridge_loop_thread() -> None:
    bridge = LoopThread()

    async def caller() -> str:
        coroutine = _value(1)
        with pytest.raises(RuntimeError, match="own event-loop thread"):
            bridge.run(coroutine)
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
        return threading.current_thread().name

    try:
        assert bridge.run(caller()) == "bap-sync-loop"
    finally:
        bridge.close()


def test_closed_bridge_fails_fast() -> None:
    bridge = LoopThread()
    bridge.close()
    coroutine = _value(1)
    with pytest.raises(RuntimeError, match="not running"):
        bridge.run(coroutine)
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


def test_fork_epoch_guard_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = LoopThread()
    try:
        monkeypatch.setattr(bridge, "_pid", -1)
        coroutine = _value(1)
        with pytest.raises(RuntimeError, match="created before fork"):
            bridge.run(coroutine)
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    finally:
        bridge.close()


def test_after_fork_resets_singleton_and_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = LoopThread()
    original_lock = bridge_module._singleton_lock
    monkeypatch.setattr(bridge_module, "_singleton", bridge)
    monkeypatch.setattr(bridge_module, "_singleton_lock", original_lock)
    try:
        bridge_module._after_fork_in_child()
        assert bridge_module._singleton is None
        assert bridge_module._singleton_lock is not original_lock
    finally:
        bridge.close()


def test_dispatcher_preserves_order_off_calling_thread() -> None:
    dispatcher = CallbackDispatcher()
    done = threading.Event()
    values: list[tuple[int, str]] = []

    def callback(value: int) -> None:
        values.append((value, threading.current_thread().name))
        if len(values) == 3:
            done.set()

    try:
        assert dispatcher.submit(callback, 1)
        assert dispatcher.submit(callback, 2)
        assert dispatcher.submit(callback, 3)
        assert done.wait(timeout=2)
        assert values == [
            (1, "bap-sync-events"),
            (2, "bap-sync-events"),
            (3, "bap-sync-events"),
        ]
    finally:
        dispatcher.close()


def test_dispatcher_survives_raising_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = CallbackDispatcher()
    done = threading.Event()

    def fail() -> None:
        raise ValueError("boom")

    try:
        caplog.set_level("ERROR", logger="browserless_bap")
        assert dispatcher.submit(fail)
        assert dispatcher.submit(done.set)
        assert done.wait(timeout=2)
        assert "bap sync event callback failed" in caplog.text
    finally:
        dispatcher.close()


def test_dispatcher_routes_callback_errors() -> None:
    dispatcher = CallbackDispatcher()
    done = threading.Event()
    errors: list[BaseException] = []

    def fail() -> None:
        raise ValueError("boom")

    def route(error: BaseException) -> None:
        errors.append(error)
        done.set()

    try:
        assert dispatcher.submit(fail, on_error=route)
        assert done.wait(timeout=2)
        assert len(errors) == 1
        assert str(errors[0]) == "boom"
    finally:
        dispatcher.close()


def test_dispatcher_overflow_drops_newest_and_logs_count(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = CallbackDispatcher(max_queue_size=1)
    started = threading.Event()
    release = threading.Event()
    queued_done = threading.Event()
    delivered: list[str] = []

    def block() -> None:
        started.set()
        release.wait(timeout=2)
        delivered.append("blocking")

    def queued() -> None:
        delivered.append("queued")
        queued_done.set()

    try:
        moments = iter((20.0, 21.0, 31.0))
        monkeypatch.setattr(time, "monotonic", lambda: next(moments))
        caplog.set_level("WARNING", logger="browserless_bap")
        assert dispatcher.submit(block)
        assert started.wait(timeout=2)
        assert dispatcher.submit(queued)
        assert not dispatcher.submit(delivered.append, "dropped")
        assert not dispatcher.submit(delivered.append, "also-dropped")
        assert not dispatcher.submit(delivered.append, "third-dropped")
        assert "dropped 1 newest callback(s)" in caplog.text
        assert "dropped 2 newest callback(s)" in caplog.text
        release.set()
        assert queued_done.wait(timeout=2)
    finally:
        release.set()
        dispatcher.close()
    assert delivered == ["blocking", "queued"]


def test_bridge_logs_tracked_browser_close_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = LoopThread()

    class FailingBrowser:
        async def close(self) -> None:
            raise RuntimeError("close failed")

    caplog.set_level("ERROR", logger="browserless_bap")
    bridge.track_browser(FailingBrowser())

    bridge.close()

    assert "Failed to close a tracked bap browser" in caplog.text
    assert "close failed" in caplog.text


def test_dead_loop_fails_pending_call_instead_of_hanging() -> None:
    bridge = LoopThread()

    async def stop_loop_mid_call() -> None:
        asyncio.get_running_loop().stop()
        await asyncio.Event().wait()

    try:
        with pytest.raises(RuntimeError, match="event loop died"):
            bridge.run(stop_loop_mid_call())
    finally:
        bridge.close()


def test_keyboard_interrupt_cancels_underlying_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = LoopThread()
    started = threading.Event()
    cleaned = threading.Event()
    real_result = cf.Future.result
    interrupted = False

    async def cancellable() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    def interrupt_once(
        future: cf.Future[object], timeout: float | None = None
    ) -> object:
        nonlocal interrupted
        if not interrupted:
            assert started.wait(timeout=2)
            interrupted = True
            raise KeyboardInterrupt
        return real_result(future, timeout)

    monkeypatch.setattr(cf.Future, "result", interrupt_once)
    try:
        with pytest.raises(KeyboardInterrupt):
            bridge.run(cancellable())
        assert cleaned.wait(timeout=2)
    finally:
        bridge.close()


def test_close_closes_tracked_browsers_before_stopping_loop() -> None:
    bridge = LoopThread()
    closed = threading.Event()

    class Browser:
        async def close(self) -> None:
            closed.set()

    bridge.track_browser(Browser())
    bridge.close()
    assert closed.is_set()


def test_post_atexit_guard_rejects_new_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "_runtime_exited", True)
    with pytest.raises(RuntimeError, match="after atexit"):
        bridge_module.get_loop_thread()


def test_close_is_idempotent() -> None:
    bridge = LoopThread()
    bridge.close()
    bridge.close()
