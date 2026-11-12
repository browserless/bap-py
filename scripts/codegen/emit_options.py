from __future__ import annotations

from .config.client_only import CLIENT_ONLY_PARAMS, CLIENT_ONLY_TYPES
from .config.methods import options_name
from .config.naming import param_name
from .config.schema_map import EXCLUDED_MUTATIONS
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
        "from .inputs import *",
        "",
        "",
    ]
    emitted: set[str] = set()
    for field in schema.mutation.fields or ():
        mutation = field.name.value
        if mutation in EXCLUDED_MUTATIONS:
            continue
        name = options_name(mutation)
        if name in emitted:
            continue
        positionals = set(schema.positionals_for(field))
        graph_fields = [
            arg for arg in field.arguments or () if arg.name.value not in positionals
        ]
        client_fields = CLIENT_ONLY_PARAMS.get(name, ())
        if not graph_fields and not client_fields:
            continue
        emitted.add(name)
        lines.append(f"class {name}(TypedDict, total=False):")
        seen: set[str] = set()
        for arg in graph_fields:
            py_name = param_name(arg.name.value)
            seen.add(py_name)
            wrapper = "Required" if is_required(arg.type) else "NotRequired"
            lines.append(f"    {py_name}: {wrapper}[{schema.python_type(arg.type)}]")
        for client in client_fields:
            if client.name in seen:
                continue
            lines.append(f"    {client.name}: NotRequired[{client.annotation}]")
        lines.extend(("", ""))
    for name, fields in CLIENT_ONLY_TYPES.items():
        lines.append(f"class {name}(TypedDict, total=False):")
        for option_field, annotation in fields.items():
            lines.append(f"    {option_field}: NotRequired[{annotation}]")
        lines.extend(("", ""))
    return "\n".join(lines).rstrip()
