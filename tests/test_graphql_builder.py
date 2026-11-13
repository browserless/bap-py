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


def test_optional_selections_preserve_nested_fields_and_deduplicate() -> None:
    from browserless_bap.graphql import selection_for

    assert selection_for("QuerySelectorResponse") == (
        "childElementCount className id innerText localName"
    )
    assert selection_for("QuerySelectorResponse", ("html",)) == (
        "childElementCount className id innerText localName innerHTML outerHTML"
    )
    assert selection_for("ResponseResponse", ("body", "bodyEncoding", "body")) == (
        "status url method type headers { name value } body base64Encoded"
    )
    assert selection_for("HTTPResponse", ("remoteMetadata",)).endswith("ip port")
    with pytest.raises(SchemaMismatchError, match="Unknown response type"):
        selection_for("Unknown")
    with pytest.raises(SchemaMismatchError, match="Unknown optional field group"):
        selection_for("QuerySelectorResponse", ("body",))
