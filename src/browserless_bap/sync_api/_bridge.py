"""Process-global asyncio bridge for the synchronous API.

One long-lived loop avoids thread churn and keeps cross-object calls loop-safe.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures as cf
import inspect
import logging
import os
import queue
import threading
import time
import warnings
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Protocol, TypeVar, cast

T = TypeVar("T")
logger = logging.getLogger("browserless_bap")


class _Closable(Protocol):
    def close(self) -> object: ...


class CallbackDispatcher:
    """Run user callbacks away from the bridge loop in emission order."""

    def __init__(self, *, max_queue_size: int = 1024) -> None:
        self._queue: queue.Queue[
            tuple[
                Callable[..., object],
                tuple[object, ...],
                Callable[[BaseException], object] | None,
            ]
            | None
        ] = queue.Queue(maxsize=max_queue_size)
        self._closed = threading.Event()
        self._last_overflow_warning = 0.0
        self._dropped_since_report = 0
        self._thread = threading.Thread(
            target=self._run,
            name="bap-sync-events",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        callback: Callable[..., object],
        *args: object,
        on_error: Callable[[BaseException], object] | None = None,
    ) -> bool:
        """Queue a callback without ever back-pressuring the socket loop."""

        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait((callback, args, on_error))
            return True
        except queue.Full:
            self._dropped_since_report += 1
            now = time.monotonic()
            if now - self._last_overflow_warning >= 10:
                self._last_overflow_warning = now
                dropped = self._dropped_since_report
                self._dropped_since_report = 0
                logger.warning(
                    "bap sync event queue is full; dropped %d newest callback(s) "
                    "since the last report",
                    dropped,
                )
            return False

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                callback, args, on_error = item
                try:
                    result = callback(*args)
                    if inspect.isawaitable(result):
                        # Close bare coroutines to avoid another unawaited warning.
                        if inspect.iscoroutine(result):
                            cast(Coroutine[object, object, object], result).close()
                        warnings.warn(
                            "sync event callbacks must not return awaitables",
                            RuntimeWarning,
                            stacklevel=2,
                        )
                except BaseException as error:
                    # Event callbacks are user code. They must not kill the
                    # singleton dispatcher or the transport loop.
                    if on_error is not None:
                        try:
                            on_error(error)
                        except BaseException:
                            logger.exception(
                                "bap sync event callback and its error router "
                                "both failed; callback error was %r",
                                error,
                            )
                    else:
                        logger.error(
                            "bap sync event callback failed",
                            exc_info=(type(error), error, error.__traceback__),
                        )
            finally:
                self._queue.task_done()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # Make room for the sentinel without blocking during interpreter
            # shutdown. Dropping one callback is preferable to deadlocking.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                return
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)


class LoopThread:
    """Own an asyncio loop on a dedicated daemon thread."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._dead_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        self._pending_lock = threading.Lock()
        self._pending: set[cf.Future[object]] = set()
        self._tracked_lock = threading.Lock()
        self._tracked_browsers: dict[int, object] = {}
        self._thread = threading.Thread(
            target=self._thread_main,
            name="bap-sync-loop",
            daemon=True,
        )
        self._dispatcher = CallbackDispatcher()
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("bap sync event loop failed to start")
        if self._loop is None:
            raise RuntimeError("bap sync event loop failed during startup")

    @property
    def dispatcher(self) -> CallbackDispatcher:
        return self._dispatcher

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        except BaseException as error:
            self._dead_error = error
        finally:
            if self._dead_error is None and not self._stopping:
                self._dead_error = RuntimeError(
                    "the bap sync event loop stopped unexpectedly"
                )
            if self._dead_error is not None:
                self._fail_pending(self._dead_error)
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                self._closed.set()

    def _check_callable_here(self) -> None:
        if os.getpid() != self._pid:
            raise RuntimeError(
                "a bap sync object created before fork cannot be used in the child; "
                "create a new Browserless connection after fork"
            )
        if self._closed.is_set() or self._dead_error is not None:
            detail = f": {self._dead_error!r}" if self._dead_error is not None else ""
            raise RuntimeError(f"the bap sync event loop is not running{detail}")
        if threading.current_thread() is self._thread:
            raise RuntimeError(
                "the bap sync API cannot be called from its own event-loop thread"
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError(
            "the bap sync API cannot run inside an active asyncio loop; "
            "use browserless_bap.async_api instead"
        )

    def run(self, awaitable: Awaitable[T], *, timeout: float | None = None) -> T:
        """Run ``awaitable`` and keep the main thread signal-responsive."""

        try:
            self._check_callable_here()
        except BaseException:
            if inspect.iscoroutine(awaitable):
                cast(Coroutine[object, object, object], awaitable).close()
            raise

        loop = self._loop
        if loop is None:
            if inspect.iscoroutine(awaitable):
                cast(Coroutine[object, object, object], awaitable).close()
            raise RuntimeError("the bap sync event loop is unavailable")

        future = asyncio.run_coroutine_threadsafe(_await(awaitable), loop)
        self._track_future(cast(cf.Future[object], future))
        deadline: float | None = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        try:
            while True:
                wait_for = 0.1
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        future.cancel()
                        raise TimeoutError(
                            f"bap sync bridge timed out after {timeout} seconds"
                        )
                    wait_for = min(wait_for, remaining)
                try:
                    return future.result(timeout=wait_for)
                except cf.TimeoutError:
                    failure = self._loop_failure()
                    if failure is not None:
                        future.cancel()
                        raise failure from None
                    continue
                except (KeyboardInterrupt, SystemExit):
                    future.cancel()
                    raise
        finally:
            self._discard_future(cast(cf.Future[object], future))

    def submit(self, awaitable: Awaitable[T]) -> cf.Future[T]:
        """Schedule cleanup work without blocking a callback thread."""

        try:
            self._check_callable_here()
        except BaseException:
            if inspect.iscoroutine(awaitable):
                cast(Coroutine[object, object, object], awaitable).close()
            raise
        loop = self._loop
        if loop is None:
            if inspect.iscoroutine(awaitable):
                cast(Coroutine[object, object, object], awaitable).close()
            raise RuntimeError("the bap sync event loop is unavailable")
        future = asyncio.run_coroutine_threadsafe(_await(awaitable), loop)
        self._track_future(cast(cf.Future[object], future))
        future.add_done_callback(
            lambda done: self._discard_future(cast(cf.Future[object], done))
        )
        return future

    def track_browser(self, browser: object) -> None:
        with self._tracked_lock:
            self._tracked_browsers[id(browser)] = browser

    def untrack_browser(self, browser: object) -> None:
        with self._tracked_lock:
            self._tracked_browsers.pop(id(browser), None)

    def close(self) -> None:
        if self._closed.is_set():
            self._dispatcher.close()
            return
        if self._stopping:
            return
        self._stopping = True
        if (
            threading.current_thread() is not self._thread
            and self._loop is not None
            and self._loop.is_running()
        ):
            with suppress(BaseException):
                self.run(self._close_tracked_browsers(), timeout=5)
        self._dispatcher.close()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)
        self._closed.set()

    async def _close_tracked_browsers(self) -> None:
        with self._tracked_lock:
            browsers = tuple(self._tracked_browsers.values())
            self._tracked_browsers.clear()
        awaitables: list[Awaitable[object]] = []
        for browser in browsers:
            try:
                result = cast(_Closable, browser).close()
                if inspect.isawaitable(result):
                    awaitables.append(cast(Awaitable[object], result))
            except BaseException:
                logger.exception("Failed to close a tracked bap browser")
                continue
        if awaitables:
            results = await asyncio.gather(*awaitables, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    logger.error(
                        "Failed to close a tracked bap browser",
                        exc_info=(type(result), result, result.__traceback__),
                    )

    def _loop_failure(self) -> RuntimeError | None:
        if self._dead_error is not None:
            return RuntimeError(
                f"the bap sync event loop is not running: {self._dead_error!r}"
            )
        if self._closed.is_set() or not self._thread.is_alive():
            return RuntimeError("the bap sync event loop is not running")
        return None

    def _track_future(self, future: cf.Future[object]) -> None:
        with self._pending_lock:
            self._pending.add(future)

    def _discard_future(self, future: cf.Future[object]) -> None:
        with self._pending_lock:
            self._pending.discard(future)

    def _fail_pending(self, error: BaseException) -> None:
        with self._pending_lock:
            pending = tuple(self._pending)
        for future in pending:
            if future.done():
                continue
            with suppress(cf.InvalidStateError):
                future.set_exception(
                    RuntimeError(f"the bap sync event loop died: {error!r}")
                )


async def _await(awaitable: Awaitable[T]) -> T:
    return await awaitable


_singleton_lock = threading.Lock()
_singleton: LoopThread | None = None
_runtime_exited = False


def get_loop_thread() -> LoopThread:
    global _singleton
    if _runtime_exited:
        raise RuntimeError(
            "the bap sync runtime is shut down; it cannot be used after atexit"
        )
    current = _singleton
    if current is not None and current._pid == os.getpid():
        return current
    with _singleton_lock:
        current = _singleton
        if current is None or current._pid != os.getpid():
            _singleton = current = LoopThread()
        return current


def shutdown() -> None:
    global _singleton
    with _singleton_lock:
        current, _singleton = _singleton, None
    if current is not None:
        current.close()


def _after_fork_in_child() -> None:
    global _singleton, _singleton_lock
    # Reset child-local state; old wrappers fail the LoopThread PID guard.
    _singleton = None
    _singleton_lock = threading.Lock()


def _atexit_shutdown() -> None:
    global _runtime_exited
    _runtime_exited = True
    shutdown()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)

atexit.register(_atexit_shutdown)
