from __future__ import annotations

import json

from .schema import Schema
from .writer import HEADER


def emit(schema: Schema) -> str:
    lines = [HEADER.rstrip(), "from typing import Literal", "", "__all__ = ["]
    for name in sorted(schema.enums):
        py_name = schema.enum_name(name)
        lines.extend((f'    "{py_name}",', f'    "{py_name}_VALUES",'))
    lines.extend(("]", ""))
    for name, node in sorted(schema.enums.items()):
        py_name = schema.enum_name(name)
        values = tuple(value.name.value for value in node.values or ())
        literal_values = [json.dumps(value) for value in values]
        literal = ", ".join(literal_values)
        if len(py_name) + len(literal) + 12 <= 88:
            lines.append(f"{py_name} = Literal[{literal}]")
        else:
            lines.append(f"{py_name} = Literal[")
            lines.extend(f"    {value}," for value in literal_values)
            lines.append("]")
        tuple_values = ", ".join(json.dumps(value) for value in values)
        if len(values) == 1:
            tuple_values += ","
        tuple_line = f"{py_name}_VALUES: tuple[{py_name}, ...] = ({tuple_values})"
        if len(tuple_line) <= 88:
            lines.append(tuple_line)
        else:
            lines.append(f"{py_name}_VALUES: tuple[{py_name}, ...] = (")
            lines.extend(f"    {value}," for value in literal_values)
            lines.append(")")
        lines.append("")
    return "\n".join(lines)
