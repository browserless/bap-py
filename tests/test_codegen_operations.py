from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from graphql import build_schema, parse, specified_rules, validate

from browserless_bap.graphql.builder import build_operation
from browserless_bap.graphql.mutations import ARG_TYPES, RESPONSE_FIELDS
from browserless_bap.graphql.subscriptions import SUBSCRIPTIONS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.schema import Schema, named_type  # noqa: E402

SOURCE = (ROOT / "src/browserless_bap/mutations.graphql").read_text(encoding="utf-8")
GRAPHQL_SCHEMA = build_schema(SOURCE)
CODEGEN_SCHEMA = Schema.load(ROOT / "src/browserless_bap/mutations.graphql")


def _assert_valid(query: str) -> None:
    errors = validate(GRAPHQL_SCHEMA, parse(query))
    assert not errors, f"{query}\n" + "\n".join(error.message for error in errors)


def _assert_valid_fragment(query: str) -> None:
    rules = [
        rule for rule in specified_rules if rule.__name__ != "NoUnusedFragmentsRule"
    ]
    errors = validate(GRAPHQL_SCHEMA, parse(query), rules=rules)
    assert not errors, f"{query}\n" + "\n".join(error.message for error in errors)


def test_every_mutation_argument_table_declares_every_argument() -> None:
    for mutation, arg_types in ARG_TYPES.items():
        field = CODEGEN_SCHEMA.mutation_fields[mutation]
        response_name = CODEGEN_SCHEMA.response_name(named_type(field.type))
        fields = RESPONSE_FIELDS.get(response_name, "__typename")
        query, _ = build_operation(
            mutation,
            dict.fromkeys(arg_types),
            fields,
            arg_types,
        )
        _assert_valid(query)


def test_every_default_and_opt_in_response_selection_is_valid() -> None:
    owner_by_response = {
        CODEGEN_SCHEMA.response_name(name): name
        for name in CODEGEN_SCHEMA.response_objects
    }
    owner_by_response.update(
        {
            "HTTPResponseWithRemoteMetadata": "HTTPResponse",
            "ResponseResponseWithBodyEncoding": "ResponseResponse",
        }
    )
    for response_name, fields in RESPONSE_FIELDS.items():
        owner = owner_by_response[response_name]
        _assert_valid_fragment(f"fragment CodegenSelection on {owner} {{ {fields} }}")


def test_every_subscription_document_is_valid() -> None:
    for event, spec in SUBSCRIPTIONS.items():
        query, _ = build_operation(
            event,
            dict.fromkeys(spec["arg_types"]),
            spec["fields"],
            spec["arg_types"],
            "subscription",
        )
        _assert_valid(query)


def test_parameterized_response_fields_are_omitted() -> None:
    assert RESPONSE_FIELDS["MapSelectorResponse"] == "innerHTML innerText id class"


@pytest.mark.parametrize(
    "args",
    [
        {
            "instructions": "**Sign in**",
            "instructionsTitle": "Login",
            "steps": ["Enter code"],
            "currentStep": 1,
            "instructionsFormat": "markdown",
            "doneLabel": "Continue",
            "failLabel": "Help",
            "requesterName": "Support",
        },
        {
            "instructions": {
                "layout": "panel",
                "format": "markdown",
                "title": "Login",
                "summary": "**Sign in**",
                "steps": ["Enter code"],
                "currentStep": 1,
            },
            "doneLabel": "Continue",
            "failLabel": "Help",
            "requesterName": "Support",
        },
        {"instructions": {"steps": ["Enter code"]}},
    ],
)
def test_live_url_serializes_strings_and_cards_with_the_server_scalar(
    args: dict[str, object],
) -> None:
    query, variables = build_operation(
        "liveURL", args, RESPONSE_FIELDS["LiveURLResponse"], ARG_TYPES["liveURL"]
    )
    assert "$instructions: StringOrInstructions" in query
    _assert_valid(query)
    assert json.loads(json.dumps(variables)) == args
