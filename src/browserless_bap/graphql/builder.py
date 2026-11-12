"""Build parameterized GraphQL-over-WebSocket operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ..errors import SchemaMismatchError


def build_operation(
    name: str,
    args: Mapping[str, object] | None,
    fields: str,
    arg_types: Mapping[str, str] | None = None,
    operation: Literal["mutation", "subscription"] = "mutation",
) -> tuple[str, dict[str, object]]:
    provided = dict(args or {})
    if not provided:
        return f"{operation} {{ {name} {{ {fields} }} }}", {}

    types = arg_types or {}
    definitions: list[str] = []
    for key in provided:
        type_name = types.get(key)
        if type_name is None:
            raise SchemaMismatchError(
                f'Missing GraphQL type for argument "{key}" of {operation} "{name}"'
            )
        definitions.append(f"${key}: {type_name}")
    variables = ", ".join(definitions)
    arguments = ", ".join(f"{key}: ${key}" for key in provided)
    query = f"{operation}({variables}) {{ {name}({arguments}) {{ {fields} }} }}"
    return query, provided


__all__ = ["build_operation"]
