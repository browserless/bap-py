from __future__ import annotations

import json
from urllib.parse import unquote

import pytest

import browserless_bap.element_handle as handles


@pytest.mark.parametrize(
    ("selector", "encoded"),
    [
        ("li", "%22li%22"),
        ("[data-q='a\"b']", "%22%5Bdata-q%3D'a%5C%22b'%5D%22"),
        ("#a\\:b", "%22%23a%5C%5C%3Ab%22"),
        (".n,\n.x", "%22.n%2C%5Cn.x%22"),
    ],
)
def test_selector_literal_matches_reference_encoding(
    selector: str, encoded: str
) -> None:
    assert handles._selector_literal(selector) == (
        f'JSON.parse(decodeURIComponent("{encoded}"))'
    )


@pytest.mark.parametrize(
    "selector",
    [
        "li",
        'a"b',
        "a\\b",
        "a\nb",
        "'!~*()",
        "%41 + %",
        "déjà ✓",
        "\U0001f600",
        "\ud800x",
        "\u2028",
    ],
)
def test_selector_literal_survives_string_interpolation(selector: str) -> None:
    literal = handles._selector_literal(selector)
    encoded = json.loads(literal.removeprefix("JSON.parse(decodeURIComponent(")[:-2])
    assert '"' not in encoded
    assert "\\" not in encoded
    assert json.loads(unquote(encoded)) == selector


@pytest.mark.parametrize("all_matches", [False, True])
def test_selector_expression_preserves_css_and_expression_fallback(
    all_matches: bool,
) -> None:
    method = "querySelectorAll" if all_matches else "querySelector"
    assert handles._selector_expression("ul", all_matches=all_matches) == (
        f"(() => {{ try {{ return document.{method}("
        'JSON.parse(decodeURIComponent("%22ul%22"))); } '
        'catch { return eval(JSON.parse(decodeURIComponent("%22ul%22"))); } })()'
    )
