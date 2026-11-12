from __future__ import annotations

import json
import keyword

from .schema import Schema, is_required
from .writer import HEADER


def emit(schema: Schema) -> str:
    lines = [
        HEADER.rstrip(),
        "# ruff: noqa: F403, F405",
        "from __future__ import annotations",
        "",
        "from typing import NotRequired, Required, TypedDict",
        "",
        "from .enums import *",
        "",
        "",
    ]
    for name, node in sorted(schema.inputs.items()):
        fields = list(node.fields or ())
        if any(keyword.iskeyword(field.name.value) for field in fields):
            lines.append(f"{name} = TypedDict(")
            lines.append(f'    "{name}",')
            lines.append("    {")
            for field in fields:
                annotation = schema.python_type(field.type)
                wrapper = "Required" if is_required(field.type) else "NotRequired"
                lines.append(
                    f"        {json.dumps(field.name.value)}: "
                    f"{json.dumps(f'{wrapper}[{annotation}]')},"
                )
            lines.extend(("    },", "    total=False,", ")", "", ""))
            continue
        lines.append(f"class {name}(TypedDict, total=False):")
        if not fields:
            lines.append("    pass")
        for field in fields:
            annotation = schema.python_type(field.type)
            wrapper = "Required" if is_required(field.type) else "NotRequired"
            lines.append(f"    {field.name.value}: {wrapper}[{annotation}]")
        lines.extend(("", ""))
    return "\n".join(lines).rstrip()
