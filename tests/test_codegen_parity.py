from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from graphql import FieldNode, OperationDefinitionNode, SelectionSetNode, parse

import browserless_bap as bap
import browserless_bap.sync_api
from browserless_bap.graphql.mutations import ARG_TYPES, RESPONSE_FIELDS
from browserless_bap.transport import MessageListener, Transport

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.config.methods import HANDWRITTEN_METHODS  # noqa: E402
from scripts.codegen.config.naming import method_name  # noqa: E402
from scripts.codegen.generate import GENERATED_OUTPUTS  # noqa: E402
from scripts.codegen.model import build_models  # noqa: E402
from scripts.codegen.schema import Schema  # noqa: E402

SNAPSHOT = json.loads((ROOT / "tests/fixtures/bap_ts_parity.json").read_text())
PY_VARIANT_OF = {
    "HTTPResponseWithRemoteMetadata": "HTTPResponse",
    "ResponseResponseWithBodyEncoding": "ResponseResponse",
}
# Fields Python still fetches by default; remove entries when they become opt-in.
KNOWN_DEFAULT_SELECTION_GAPS = {
    "QuerySelectorResponse": {"innerHTML", "outerHTML"},
    "ResponseResponse": {"body"},
}
# These lack bap-ts's 5-second headroom; remove each entry as it gains it.
KNOWN_TIMEOUT_GAPS = {
    "back",
    "checkbox",
    "click",
    "content",
    "evaluate",
    "forward",
    "goto",
    "hover",
    "html",
    "mapSelector",
    "markdown",
    "preferences",
    "querySelector",
    "querySelectorAll",
    "reconnect",
    "reload",
    "request",
    "response",
    "scroll",
    "solve",
    "solveImageCaptcha",
    "switchToWindow",
    "text",
    "type",
    "waitForNavigation",
    "waitForNetworkIdle",
    "waitForRequest",
    "waitForSelector",
}
TIMEOUT_NOT_MEASURED = {
    "liveURL": "needs the completion subscription; covered by the live-URL tests",
}
CALLS: dict[str, tuple[str, tuple[Any, ...], dict[str, Any]]] = {
    "back": ("go_back", (), {}),
    "checkbox": ("check", ("#a",), {}),
    "click": ("click", ("#a",), {}),
    "content": ("set_content", ("<p></p>",), {}),
    "evaluate": ("evaluate", ("1",), {}),
    "forward": ("go_forward", (), {}),
    "goto": ("goto", ("https://example.com",), {}),
    "hover": ("hover", ("#a",), {}),
    "html": ("html", (), {}),
    "mapSelector": ("map_selector", ("#a",), {}),
    "markdown": ("markdown", (), {}),
    "preferences": ("preferences", (), {}),
    "querySelector": ("query_selector", ("#a",), {}),
    "querySelectorAll": ("query_selector_all", ("#a",), {}),
    "reconnect": ("reconnect", (), {}),
    "reload": ("reload", (), {}),
    "request": ("request", (), {}),
    "response": ("response", (), {}),
    "scroll": ("scroll", (), {}),
    "solve": ("solve", (), {}),
    "solveImageCaptcha": (
        "solve_image_captcha",
        (),
        {"captcha_selector": "#c", "input_selector": "#i"},
    ),
    "switchToWindow": ("switch_to_window", (), {}),
    "text": ("text", (), {}),
    "type": ("type", ("#a", "t"), {}),
    "waitForEvent": ("wait_for_event", ("load",), {}),
    "waitForFunction": ("wait_for_function", ("() => 1",), {}),
    "waitForNavigation": ("wait_for_navigation", (), {}),
    "waitForNetworkIdle": ("wait_for_network_idle", (), {}),
    "waitForRequest": ("wait_for_request", ("https://example.com",), {}),
    "waitForSelector": ("wait_for_selector", ("#a",), {}),
}


def test_snapshot_matches_vendored_schema() -> None:
    assert (
        SNAPSHOT["schema_sha256"]
        == sha256(
            (ROOT / "src/browserless_bap/mutations.graphql").read_bytes()
        ).hexdigest()
    ), (
        "Re-run scripts/bap_ts_parity.py for the bap-ts version "
        "the schema was synced from"
    )


def test_every_bap_ts_method_has_a_python_name() -> None:
    ts_methods = set(SNAPSHOT["methods"])
    expected = {method_name(name) for name in ts_methods}

    schema = Schema.load(ROOT / "src/browserless_bap/mutations.graphql")
    generated = {model.py_name for model in build_models(schema)}
    handwritten = {name for name, _, _ in HANDWRITTEN_METHODS}
    assert expected == generated | handwritten
    assert all(hasattr(bap.Page, name) for name in expected)
    assert all(hasattr(bap.sync_api.Page, name) for name in expected)


def test_arg_types_match_bap_ts() -> None:
    assert {key: value for key, value in ARG_TYPES.items() if value} == SNAPSHOT[
        "arg_types"
    ]


def selection_paths(fields: str) -> set[str]:
    def paths(selections: SelectionSetNode, prefix: str = "") -> set[str]:
        result = set()
        for field in selections.selections:
            assert isinstance(field, FieldNode)
            path = prefix + field.name.value
            result.add(path)
            if field.selection_set is not None:
                result |= paths(field.selection_set, path + ".")
        return result

    operation = parse("{" + fields + "}").definitions[0]
    assert isinstance(operation, OperationDefinitionNode)
    return paths(operation.selection_set)


def test_response_fields_match_bap_ts() -> None:
    assert set(RESPONSE_FIELDS) - set(PY_VARIANT_OF) == set(SNAPSHOT["response_fields"])
    for name, fields in SNAPSHOT["response_fields"].items():
        python = selection_paths(RESPONSE_FIELDS[name])
        for variant, base in PY_VARIANT_OF.items():
            if base == name:
                python |= selection_paths(RESPONSE_FIELDS[variant])
        typescript = selection_paths(fields)
        for group in SNAPSHOT["optional_fields"].get(name, {}).values():
            typescript |= selection_paths(group)
        assert python == typescript, name


def test_default_selection_gaps_are_exactly_known() -> None:
    actual = {}
    for name, fields in SNAPSHOT["response_fields"].items():
        python, typescript = (
            selection_paths(RESPONSE_FIELDS[name]),
            selection_paths(fields),
        )
        assert not typescript - python, name
        if python - typescript:
            actual[name] = python - typescript
    assert actual == KNOWN_DEFAULT_SELECTION_GAPS


class _Stop(Exception):
    pass


class DeadlineTransport:
    closed = False
    deadline: float | None = None

    def on_message(self, _listener: MessageListener) -> Callable[[], None]:
        return lambda: None

    def operation_timeout(self, timeout: float | None, cushion: float = 0) -> float:
        resolved = 30_000 if timeout is None else timeout
        return resolved + cushion if resolved > 0 else resolved

    async def send(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> dict[str, Any]:
        self.deadline = self.operation_timeout(timeout)
        raise _Stop

    async def close(self) -> None:
        self.closed = True


async def test_timeout_cushion_matches_bap_ts() -> None:
    cushioned = set(SNAPSHOT["cushioned_mutations"])
    assert set(TIMEOUT_NOT_MEASURED) <= cushioned
    assert set(CALLS) == cushioned - set(TIMEOUT_NOT_MEASURED)
    gaps = set()
    for mutation in sorted(cushioned - set(TIMEOUT_NOT_MEASURED)):
        name, args, kwargs = CALLS[mutation]
        transport = DeadlineTransport()
        page = bap.Page(cast(Transport, transport))
        try:
            try:
                await getattr(page, name)(*args, timeout=1000, **kwargs)
            except _Stop:
                pass
            else:
                raise AssertionError(f"{mutation} did not reach Transport.send")
        finally:
            await page.close()
        assert transport.deadline == (
            1000 if mutation in KNOWN_TIMEOUT_GAPS else 6000
        ), mutation
        if transport.deadline != 6000:
            gaps.add(mutation)
    assert gaps == KNOWN_TIMEOUT_GAPS


def test_generated_outputs_are_declared_and_present() -> None:
    assert all((ROOT / output).is_file() for output in GENERATED_OUTPUTS)
