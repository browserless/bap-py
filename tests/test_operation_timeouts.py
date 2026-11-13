from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from browserless_bap.page import Page
from browserless_bap.transport import MessageListener, Transport


class RecordingTransport:
    closed = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, float | None]] = []

    def on_message(self, _listener: MessageListener) -> Callable[[], None]:
        return lambda: None

    def operation_timeout(self, timeout: float | None, cushion: float = 0) -> float:
        resolved = 30_000 if timeout is None else timeout
        return resolved + cushion if resolved > 0 else resolved

    async def send(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        _timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append((query, variables, _timeout))
        return {}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("goto", ("https://example.com",), {"timeout": 1500}, 6500),
        ("goto", ("https://example.com",), {}, 35000),
        ("wait_for_selector", ("#missing",), {"timeout": 0}, 0),
        ("content", (), {}, 35000),
        ("select_option", ("select", "value"), {}, 35000),
        ("evaluate", ("1 + 1",), {"timeout": 1500}, 6500),
        ("wait_for_request", (), {"timeout": 1500}, 6500),
        ("wait_for_function", ("() => true",), {"timeout": 500}, 5500),
        ("wait_for_event", ("load",), {"timeout": 500}, 5500),
        ("wait_for_timeout", (1000,), {}, 6000),
        ("wait_for_response", (), {"timeout": 1500}, 1500),
        ("send", ("query { title { title } }",), {"timeout": 1500}, 1500),
    ],
)
async def test_operation_deadline_cushions_only_remote_timeouts(
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected: float,
) -> None:
    transport = RecordingTransport()
    page = Page(cast(Transport, transport))

    await getattr(page, method)(*args, **kwargs)

    assert len(transport.calls) == 1
    _, variables, deadline = transport.calls[0]
    assert deadline == expected
    if "timeout" in kwargs and method not in {"send", "wait_for_response"}:
        assert variables is not None
        assert variables["timeout"] == kwargs["timeout"]
    await page.close()
