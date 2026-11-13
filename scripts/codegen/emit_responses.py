from __future__ import annotations

import json
import keyword

from .config.schema_map import RESPONSE_FIELD_TYPE_OVERRIDES
from .schema import Schema
from .writer import HEADER


def _nullable(annotation: str) -> str:
    return annotation if annotation.endswith(" | None") else f"{annotation} | None"


def emit(schema: Schema) -> str:
    lines = [
        HEADER.rstrip(),
        "# ruff: noqa: F403, F405",
        "from __future__ import annotations",
        "",
        "from typing import NotRequired, TypedDict",
        "",
        "from .enums import *",
        "",
        "",
    ]
    for gql_name, node in sorted(schema.response_objects.items()):
        name = schema.response_name(gql_name)
        fields = [field for field in node.fields or () if not field.arguments]
        if any(keyword.iskeyword(field.name.value) for field in fields):
            lines.append("# Functional syntax is required for Python keyword fields.")
            lines.append(f"{name} = TypedDict(")
            lines.append(f'    "{name}",')
            lines.append("    {")
            for field in fields:
                annotation = _nullable(
                    RESPONSE_FIELD_TYPE_OVERRIDES.get(
                        (gql_name, field.name.value),
                        schema.python_type(field.type, response=True),
                    )
                )
                lines.append(
                    f"        {json.dumps(field.name.value)}: "
                    f"{json.dumps(f'NotRequired[{annotation}]')},"
                )
            lines.extend(("    },", "    total=False,", ")", "", ""))
            continue
        lines.append(f"class {name}(TypedDict, total=False):")
        if not fields:
            lines.append("    pass")
        for field in fields:
            annotation = _nullable(
                RESPONSE_FIELD_TYPE_OVERRIDES.get(
                    (gql_name, field.name.value),
                    schema.python_type(field.type, response=True),
                )
            )
            lines.append(f"    {field.name.value}: NotRequired[{annotation}]")
        lines.extend(("", ""))
    return "\n".join(lines).rstrip()
