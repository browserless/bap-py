from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.config.methods import (  # noqa: E402
    HANDWRITTEN_METHODS,
    PAGE_EXCLUDED,
    POSITIONAL_ARGS,
)
from scripts.codegen.config.schema_map import OPTIONAL_FIELDS, SCALAR_MAP  # noqa: E402
from scripts.codegen.model import build_models  # noqa: E402
from scripts.codegen.schema import Schema  # noqa: E402


def test_larger_schema_baseline_and_config_validate() -> None:
    schema_path = ROOT / "src/browserless_bap/mutations.graphql"
    schema = Schema.load(schema_path)

    assert len(schema.source.splitlines()) == 5560
    assert len(schema.mutation_fields) == 57
    assert {"console", "request", "response", "liveComplete"} == set(
        schema.subscription_fields
    )


def test_one_ir_covers_generated_and_handwritten_method_table() -> None:
    schema = Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    models = build_models(schema)

    assert len(models) == 49
    assert len(models) + len(HANDWRITTEN_METHODS) == 62
    assert len({model.py_name for model in models}) == len(models)
    assert {model.flavor for model in models} == {
        "buffer",
        "element",
        "element_list",
        "list",
        "plain",
        "unwrap",
    }


def test_client_only_parameters_have_no_wire_name() -> None:
    schema = Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    models = {model.py_name: model for model in build_models(schema)}

    goto = {param.py_name: param for param in models["goto"].params}
    response = {param.py_name: param for param in models["response"].params}
    assert goto["remote_response_metadata"].gql_name is None
    assert response["body_encoding"].gql_name is None
    assert response["body"].gql_name is None
    for name in ("query_selector", "query_selector_all"):
        assert (
            next(p for p in models[name].params if p.py_name == "html").gql_name is None
        )


def test_stale_mutation_config_fails_loud() -> None:
    PAGE_EXCLUDED.add("staleMutation")
    try:
        with pytest.raises(ValueError, match="unknown mutation 'staleMutation'"):
            Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    finally:
        PAGE_EXCLUDED.remove("staleMutation")


def test_stale_positional_argument_fails_loud() -> None:
    previous = POSITIONAL_ARGS["hover"]
    POSITIONAL_ARGS["hover"] = (*previous, "staleArgument")
    try:
        with pytest.raises(ValueError, match="unknown argument 'staleArgument'"):
            Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    finally:
        POSITIONAL_ARGS["hover"] = previous


def test_unmapped_custom_scalar_fails_loud() -> None:
    previous = SCALAR_MAP.pop("FloatOrString")
    try:
        with pytest.raises(ValueError, match="unmapped custom scalar 'FloatOrString'"):
            Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    finally:
        SCALAR_MAP["FloatOrString"] = previous


@pytest.mark.parametrize(
    ("type_name", "field", "message"),
    [
        ("MissingType", "body", "unknown type 'MissingType'"),
        ("ResponseResponse", "missingField", "unknown field 'missingField'"),
    ],
)
def test_invalid_optional_field_configuration_fails_loud(
    type_name: str,
    field: str,
    message: str,
) -> None:
    previous = OPTIONAL_FIELDS.get(type_name)
    OPTIONAL_FIELDS[type_name] = {"invalid": (field,)}
    try:
        with pytest.raises(ValueError, match=message):
            Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    finally:
        if previous is None:
            del OPTIONAL_FIELDS[type_name]
        else:
            OPTIONAL_FIELDS[type_name] = previous
