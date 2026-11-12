from __future__ import annotations

from .schema import Schema
from .writer import HEADER


def emit(schema: Schema) -> str:
    del schema
    return "\n".join(
        (
            HEADER.rstrip(),
            "# ruff: noqa: F403",
            "from .enums import *",
            "from .events import *",
            "from .inputs import *",
            "from .options import *",
            "from .responses import *",
            "",
        )
    )
