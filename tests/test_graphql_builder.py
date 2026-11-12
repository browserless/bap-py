from __future__ import annotations

import pytest

from browserless_bap.errors import SchemaMismatchError
from browserless_bap.graphql.builder import build_operation


def test_builds_parameterized_operation_and_preserves_explicit_null() -> None:
    query, variables = build_operation(
        "goto",
        {"url": "https://example.com", "referer": None},
        "status url",
        {"url": "String!", "referer": "String"},
    )

    assert query == (
        "mutation($url: String!, $referer: String) "
        "{ goto(url: $url, referer: $referer) { status url } }"
    )
    assert variables == {"url": "https://example.com", "referer": None}


def test_builds_argument_free_subscription() -> None:
    assert build_operation("console", None, "type text", operation="subscription") == (
        "subscription { console { type text } }",
        {},
    )


def test_missing_argument_type_is_a_schema_mismatch() -> None:
    with pytest.raises(SchemaMismatchError, match="Missing GraphQL type"):
        build_operation("goto", {"url": "https://example.com"}, "status")
