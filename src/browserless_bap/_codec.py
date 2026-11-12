"""Small zero-conversion helpers shared by generated Page methods."""

from __future__ import annotations

from typing import TypeVar

from ._io import decode_base64, write_binary_file
from ._unset import UNSET, UnsetType

T = TypeVar("T")


def drop_unset(values: dict[str, object]) -> dict[str, object] | None:
    result = {key: value for key, value in values.items() if value is not UNSET}
    return result or None


def or_default(value: T | None, default: T) -> T:
    return default if value is None else value


__all__ = [
    "UNSET",
    "UnsetType",
    "decode_base64",
    "drop_unset",
    "or_default",
    "write_binary_file",
]
