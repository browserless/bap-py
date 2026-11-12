"""Non-blocking file and base64 helpers."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path


def decode_base64(value: str) -> bytes:
    """Decode the server's lenient, sometimes-unpadded base64 strings."""

    compact = "".join(value.split())
    compact += "=" * (-len(compact) % 4)
    return base64.b64decode(compact, validate=False)


async def read_text_file(path: str | Path) -> str:
    """Read UTF-8 text without blocking the transport event loop."""

    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


async def write_binary_file(path: str | Path, data: bytes) -> None:
    """Write bytes without blocking the transport event loop."""

    await asyncio.to_thread(Path(path).write_bytes, data)
