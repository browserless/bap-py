"""Build parameterized GraphQL-over-WebSocket operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from ..errors import SchemaMismatchError
from .mutations import OPTIONAL_FIELDS, RESPONSE_FIELDS


def selection_for(response_type: str, opt_in: Iterable[str] = ()) -> str:
    base = RESPONSE_FIELDS.get(response_type)
    if base is None:
        raise SchemaMismatchError(f"Unknown response type: {response_type}")
    selected: dict[str, None] = {}
    for group in opt_in:
        fields = OPTIONAL_FIELDS.get(response_type, {}).get(group)
        if fields is None:
            raise SchemaMismatchError(
                f'Unknown optional field group "{group}" '
                f"for response type {response_type}"
            )
        selected.update(dict.fromkeys(fields.split()))
    return " ".join((base, *selected))


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


__all__ = ["build_operation", "selection_for"]
