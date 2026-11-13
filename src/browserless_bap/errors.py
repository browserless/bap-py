"""Typed public exceptions raised by :mod:`browserless_bap`."""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from typing import ClassVar, Literal

ErrorCode = Literal["BQL", "CONNECTION", "TIMEOUT", "CLIENT"]

__all__ = [
    "BAPConnectionError",
    "BAPError",
    "BAPTimeoutError",
    "BAPValueError",
    "BrowserQLError",
    "ErrorCode",
    "SchemaMismatchError",
]


class BAPError(Exception):
    """Base class for errors produced by the SDK."""

    code: ClassVar[ErrorCode] = "CLIENT"


class BrowserQLError(BAPError):
    """The GraphQL operation returned one or more errors."""

    code = "BQL"

    def __init__(self, errors: Sequence[object]) -> None:
        self.errors = [
            dict(error) if isinstance(error, Mapping) else {"message": str(error)}
            for error in errors
        ]
        message = "; ".join(
            str(error.get("message", "Unknown BrowserQL error"))
            for error in self.errors
        )
        super().__init__(message or "Unknown BrowserQL error")


class BAPConnectionError(BAPError, builtins.ConnectionError):
    """The BAP transport could not connect or disconnected."""

    code = "CONNECTION"


class BAPTimeoutError(BAPError, builtins.TimeoutError):
    """A BAP operation exceeded its transport deadline."""

    code = "TIMEOUT"

    def __init__(self, operation: str, timeout_ms: float) -> None:
        self.operation = operation
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Operation timed out after {timeout_ms:g}ms: {operation[:50]}"
        )


class SchemaMismatchError(BAPError):
    """The generated schema metadata and runtime call site disagree."""

    code = "CLIENT"


class BAPValueError(BAPError, builtins.ValueError):
    """A public SDK argument failed client-side validation."""

    code = "CLIENT"
