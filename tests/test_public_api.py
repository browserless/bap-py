import builtins
import importlib
import inspect
import sys
from pathlib import Path
from typing import NotRequired, get_type_hints

import pytest

from browserless_bap import errors
from browserless_bap.page import Page
from browserless_bap.sync_api.page import Page as SyncPage
from browserless_bap.types.responses import QuerySelectorResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.model import build_models  # noqa: E402
from scripts.codegen.schema import Schema  # noqa: E402


@pytest.mark.parametrize(
    "module_name",
    ["browserless_bap", "browserless_bap.async_api", "browserless_bap.errors"],
)
def test_public_imports_do_not_shadow_builtins(module_name: str) -> None:
    module = importlib.import_module(module_name)
    namespace: dict[str, object] = {}
    exec(f"from {module_name} import *", namespace)
    for name in ("ConnectionError", "TimeoutError", "ValueError"):
        assert not hasattr(module, name)
        assert name not in namespace
        assert eval(name, namespace) is getattr(builtins, name)


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("BAPConnectionError", builtins.ConnectionError),
        ("BAPTimeoutError", builtins.TimeoutError),
        ("BAPValueError", builtins.ValueError),
    ],
)
def test_sdk_errors_have_distinct_names_and_builtin_bases(
    name: str, base: type[Exception]
) -> None:
    error = getattr(errors, name)
    assert error.__name__ == name
    assert issubclass(error, errors.BAPError)
    assert issubclass(error, base)


def test_errors_export_public_error_types_and_code() -> None:
    assert set(errors.__all__) == {
        "BAPError",
        "BAPConnectionError",
        "BAPTimeoutError",
        "BAPValueError",
        "BrowserQLError",
        "ErrorCode",
        "SchemaMismatchError",
    }


def test_generated_methods_have_clean_docstrings() -> None:
    models = build_models(Schema.load(ROOT / "src/browserless_bap/mutations.graphql"))
    for model in models:
        for page in (Page, SyncPage):
            doc = inspect.getdoc(getattr(page, model.py_name))
            assert doc, model.py_name
            assert "```" not in doc
            assert "**Field Definition" not in doc


def test_selector_eval_docs_explain_difference_from_playwright() -> None:
    readme = (ROOT / "README.md").read_text()
    for name in ("eval_on_selector", "eval_on_selector_all"):
        for page in (Page, SyncPage):
            assert "Unlike Playwright" in (inspect.getdoc(getattr(page, name)) or "")
        row = next(line for line in readme.splitlines() if f"`{name}`" in line)
        assert row.endswith("| — |")


def test_child_element_count_is_typed_as_an_integer() -> None:
    assert (
        get_type_hints(QuerySelectorResponse, include_extras=True)["childElementCount"]
        == NotRequired[int | None]
    )
