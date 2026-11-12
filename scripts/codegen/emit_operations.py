from __future__ import annotations

# Data-table assignment templates are kept atomic for deterministic output.
# ruff: noqa: E501
import json

from .config.schema_map import UNSUPPORTED_FIELDS
from .schema import Schema, render_graphql_type
from .writer import HEADER


def response_fields(schema: Schema) -> dict[str, str]:
    fields = {
        schema.response_name(name): schema.response_selection(name)
        for name in schema.response_objects
    }
    for name, config in UNSUPPORTED_FIELDS.items():
        fields[str(config["variant"])] = schema.response_selection(
            name, keep_unsupported=True
        )
    return fields


def argument_types(schema: Schema) -> dict[str, dict[str, str]]:
    return {
        field.name.value: {
            arg.name.value: render_graphql_type(arg.type)
            for arg in field.arguments or ()
        }
        for field in schema.mutation.fields or ()
    }


def emit(schema: Schema) -> str:
    return "\n".join(
        (
            HEADER.rstrip(),
            "from __future__ import annotations",
            "",
            "# fmt: off",
            f"RESPONSE_FIELDS: dict[str, str] = {json.dumps(response_fields(schema), sort_keys=True, indent=4)}",
            "",
            f"ARG_TYPES: dict[str, dict[str, str]] = {json.dumps(argument_types(schema), sort_keys=True, indent=4)}",
            "# fmt: on",
            "",
        )
    )
