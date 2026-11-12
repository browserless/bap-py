from __future__ import annotations

import ast
import sys
from pathlib import Path

from graphql import parse
from graphql.language import ObjectTypeDefinitionNode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.emit_events import emit_types  # noqa: E402
from scripts.codegen.emit_page import _literal  # noqa: E402
from scripts.codegen.schema import Schema  # noqa: E402


def _schema(source: str) -> Schema:
    objects = {
        definition.name.value: definition
        for definition in parse(source).definitions
        if isinstance(definition, ObjectTypeDefinitionNode)
    }
    return Schema(
        source=source,
        enums={},
        inputs={},
        objects=objects,
        scalars=set(),
        mutation=objects["Mutation"],
        subscription=objects.get("Subscription"),
        response_overrides={},
    )


def test_nested_injected_values_render_as_python_literals() -> None:
    value = {
        "enabled": True,
        "fallback": None,
        "values": [False, {"nested": True}],
    }

    assert ast.literal_eval(_literal(value)) == value


def test_event_name_literal_is_valid_without_schema_subscriptions() -> None:
    generated = emit_types(_schema("type Mutation { ping: String }\n"))

    assert 'EventName = Literal["error", "message"]' in generated
    ast.parse(generated)


def test_response_selection_omits_recursive_object_edges() -> None:
    schema = _schema(
        "\n".join(
            (
                "type Mutation { root: Node }",
                "type Node { value: String child: Node }",
            )
        )
    )

    assert schema.response_selection("Node") == "value child { value }"
