import asyncio

import pytest

from browserless_bap.emitter import EventEmitter


def test_order_dedup_once_and_count_hooks() -> None:
    changes: list[tuple[str, int]] = []
    seen: list[str] = []
    emitter = EventEmitter(lambda event, count: changes.append((event, count)))

    def first(_payload: object) -> None:
        seen.append("first")

    emitter.on("ping", first)
    emitter.on("ping", first)
    emitter.once("ping", lambda _payload: seen.append("once"))
    assert emitter.emit("ping", 1)
    assert emitter.emit("ping", 2)

    assert seen == ["first", "once", "first"]
    assert emitter.listener_count("ping") == 1
    assert changes == [("ping", 1), ("ping", 2), ("ping", 1)]


def test_once_listener_can_be_removed_by_original_callback() -> None:
    emitter = EventEmitter()
    seen: list[object] = []
    listener = seen.append

    emitter.once("ping", listener)
    emitter.off("ping", listener)

    assert not emitter.emit("ping", 1)
    assert seen == []


@pytest.mark.asyncio
async def test_async_listener_is_scheduled_and_errors_are_routed() -> None:
    emitter = EventEmitter()
    delivered = asyncio.Event()
    errors: list[BaseException] = []

    async def listener(_payload: object) -> None:
        delivered.set()
        raise RuntimeError("listener failed")

    emitter.on("error", errors.append)
    emitter.on("ping", listener)
    emitter.emit("ping", None)
    await asyncio.wait_for(delivered.wait(), 1)
    await asyncio.sleep(0)

    assert len(errors) == 1
    assert str(errors[0]) == "listener failed"


@pytest.mark.asyncio
async def test_async_listener_task_preserves_cancellation() -> None:
    emitter = EventEmitter()
    started = asyncio.Event()
    release = asyncio.Event()
    errors: list[BaseException] = []

    async def listener(_payload: object) -> None:
        started.set()
        await release.wait()

    emitter.on("error", errors.append)
    emitter.on("ping", listener)
    emitter.emit("ping", None)
    await started.wait()
    task = next(iter(emitter._tasks))

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert errors == []


def test_self_removal_does_not_perturb_current_delivery() -> None:
    emitter = EventEmitter()
    seen: list[str] = []

    def first(_payload: object) -> None:
        seen.append("first")
        emitter.off("ping", first)

    emitter.on("ping", first)
    emitter.on("ping", lambda _payload: seen.append("second"))
    emitter.emit("ping", None)
    assert seen == ["first", "second"]


def test_async_listener_without_running_loop_routes_error() -> None:
    emitter = EventEmitter()
    errors: list[BaseException] = []

    async def listener(_payload: object) -> None:
        return None

    emitter.on("error", errors.append)
    emitter.on("ping", listener)

    emitter.emit("ping", None)

    assert len(errors) == 1
    assert str(errors[0]) == "Async event listener requires a running event loop"


def test_error_listener_failure_uses_last_resort_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    emitter = EventEmitter()

    def fail(_payload: object) -> None:
        raise RuntimeError("double fault")

    caplog.set_level("ERROR", logger="browserless_bap")
    emitter.on("error", fail)
    emitter.on("ping", fail)

    emitter.emit("ping", None)

    assert "Unhandled exception in bap error event listener" in caplog.text
    assert "double fault" in caplog.text


def test_missing_error_listener_uses_last_resort_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    emitter = EventEmitter()

    def fail(_payload: object) -> None:
        raise RuntimeError("unhandled")

    caplog.set_level("ERROR", logger="browserless_bap")
    emitter.on("ping", fail)

    emitter.emit("ping", None)

    assert "Unhandled bap event listener exception" in caplog.text
    assert "unhandled" in caplog.text
