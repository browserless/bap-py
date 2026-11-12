from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import browserless_bap as bap
import browserless_bap.sync_api

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.config.methods import HANDWRITTEN_METHODS  # noqa: E402
from scripts.codegen.config.naming import method_name  # noqa: E402
from scripts.codegen.generate import GENERATED_OUTPUTS  # noqa: E402
from scripts.codegen.model import build_models  # noqa: E402
from scripts.codegen.schema import Schema  # noqa: E402

TS_README = ROOT.parent / "bap-ts/README.md"


@pytest.mark.skipif(not TS_README.exists(), reason="sibling bap-ts is absent")
def test_every_bap_ts_method_has_a_python_name() -> None:
    readme = TS_README.read_text(encoding="utf-8")
    block = readme.split("<!-- AUTOGEN:method-table START -->", 1)[1].split(
        "<!-- AUTOGEN:method-table END -->", 1
    )[0]
    ts_methods = {
        match.group(1)
        for match in re.finditer(r"^\| `([^`]+)` \|", block, re.MULTILINE)
    }
    expected = {method_name(name) for name in ts_methods}

    schema = Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    generated = {model.py_name for model in build_models(schema)}
    handwritten = {name for name, _, _ in HANDWRITTEN_METHODS}
    assert expected == generated | handwritten
    assert all(hasattr(bap.Page, name) for name in expected)
    assert all(hasattr(bap.sync_api.Page, name) for name in expected)


def test_generated_outputs_are_declared_and_present() -> None:
    assert all((ROOT / output).is_file() for output in GENERATED_OUTPUTS)
