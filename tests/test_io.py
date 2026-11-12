import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import ParamSpec, TypeVar

import pytest

from browserless_bap._io import decode_base64, read_text_file, write_binary_file

P = ParamSpec("P")
R = TypeVar("R")


def test_decode_base64_accepts_unpadded_and_whitespace() -> None:
    assert decode_base64(" aGVs\nbG8 ") == b"hello"


@pytest.mark.asyncio
async def test_file_helpers_use_to_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(
        function: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        nonlocal calls
        calls += 1
        return await real_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    text_path = tmp_path / "source.js"
    text_path.write_text("hello", encoding="utf-8")
    binary_path = tmp_path / "shot.png"

    assert await read_text_file(text_path) == "hello"
    await write_binary_file(binary_path, b"\x89PNG")
    assert binary_path.read_bytes() == b"\x89PNG"
    assert calls == 2
