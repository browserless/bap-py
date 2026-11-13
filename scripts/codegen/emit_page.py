"""Async and sync Page method emitters consuming the shared method IR."""

# Long strings below are templates whose emitted output is wrapped separately.
# ruff: noqa: E501

from __future__ import annotations

import json

from .model import MethodModel
from .writer import HEADER


def _literal(value: object) -> str:
    if value is True:
        return "True"
    if value is False:
        return "False"
    if value is None:
        return "None"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return f"[{', '.join(_literal(item) for item in value)}]"
    if isinstance(value, tuple):
        suffix = "," if len(value) == 1 else ""
        return f"({', '.join(_literal(item) for item in value)}{suffix})"
    if isinstance(value, dict):
        entries = (f"{_literal(key)}: {_literal(item)}" for key, item in value.items())
        return f"{{{', '.join(entries)}}}"
    return repr(value)


def _signature_lines(model: MethodModel, indent: str = "    ") -> list[str]:
    positional = [param for param in model.params if param.positional]
    keyword = [param for param in model.params if not param.positional]
    parts = [f"{param.py_name}: {param.annotation}," for param in positional]
    if keyword:
        parts.append("*,")
    for param in keyword:
        if param.required:
            parts.append(f"{param.py_name}: {param.annotation},")
        else:
            parts.append(f"{param.py_name}: {param.annotation} | UnsetType = UNSET,")
    return [f"{indent}self,", *(f"{indent}{part}" for part in parts)]


def _argument_lines(model: MethodModel) -> list[str]:
    values = {
        param.gql_name: param.py_name
        for param in model.params
        if param.gql_name is not None
    }
    values.update({key: _literal(value) for key, value in model.inject.items()})
    if not values:
        return ["        args = None"]
    lines = ["        args = drop_unset(", "            {"]
    lines.extend(
        f"                {json.dumps(key)}: {value}," for key, value in values.items()
    )
    lines.extend(("            }", "        )"))
    return lines


def _execute_lines(model: MethodModel, prefix: str) -> list[str]:
    timeout = model.transport_timeout_param
    lines = [
        f"        {prefix}self._execute(",
        f"            {json.dumps(model.mutation)},",
        "            args,",
        f"            {json.dumps(model.response_type)},",
    ]
    if timeout is not None:
        lines.append(f"            timeout=None if {timeout} is UNSET else {timeout},")
    lines.extend(_opt_in_lines(model, "            "))
    lines.append("        )")
    return lines


def _cast_execute_lines(model: MethodModel) -> list[str]:
    timeout = model.transport_timeout_param
    lines = [
        "        return cast(",
        f"            {json.dumps(model.return_type)},",
        "            await self._execute(",
        f"                {json.dumps(model.mutation)},",
        "                args,",
        f"                {json.dumps(model.response_type)},",
    ]
    if timeout is not None:
        lines.append(
            f"                timeout=None if {timeout} is UNSET else {timeout},"
        )
    lines.extend(_opt_in_lines(model, "                "))
    lines.extend(("            ),", "        )"))
    return lines


def _opt_in_lines(model: MethodModel, indent: str) -> list[str]:
    params = [param for param in model.params if param.opt_in is not None]
    if not params:
        return []
    entries = ", ".join(
        f"({json.dumps(param.opt_in)}, {param.py_name})" for param in params
    )
    return [
        f"{indent}opt_in=tuple(",
        f"{indent}    group",
        f"{indent}    for group, enabled in ({entries},)",
        f"{indent}    if enabled is True",
        f"{indent}),",
    ]


def _async_method(model: MethodModel) -> list[str]:
    lines = [f"    async def {model.py_name}("]
    lines.extend(_signature_lines(model, "        "))
    lines.append(f"    ) -> {model.return_type}:")
    if docstring := model.doc:
        lines.append(f"        {json.dumps(docstring, ensure_ascii=False)}")
    lines.extend(_argument_lines(model))
    if model.flavor == "buffer":
        has_path = any(param.py_name == "path" for param in model.params)
        lines.extend(
            (
                *_execute_lines(model, "result = await "),
                '        data = decode_base64((result or {}).get("base64") or "")',
            )
        )
        if has_path:
            lines.extend(
                (
                    "        if path is not UNSET:",
                    "            await write_binary_file(path, data)",
                )
            )
        lines.append("        return data")
    elif model.flavor == "element":
        selector = next(param.py_name for param in model.params if param.positional)
        lines.extend(
            (
                *_execute_lines(model, "result = await "),
                "        if result is None:",
                "            return None",
                "        from .element_handle import ElementHandle",
                "",
                f'        return ElementHandle(cast("Page", self), {selector}, result)',
            )
        )
    elif model.flavor == "element_list":
        selector = next(param.py_name for param in model.params if param.positional)
        lines.extend(
            (
                *_execute_lines(model, "results = await "),
                "        if not results:",
                "            return []",
                "        from .element_handle import ElementHandle, _selector_expression",
                "",
                f"        expression = _selector_expression({selector}, all_matches=True)",
                "        return [",
                '            ElementHandle(cast("Page", self), f"({expression})[{index}]", item)',
                "            for index, item in enumerate(results)",
                "        ]",
            )
        )
    elif model.flavor == "unwrap":
        lines.extend(
            (
                *_execute_lines(model, "result = await "),
                "        return cast(",
                f"            {json.dumps(model.return_type)},",
                "            or_default(",
                f"                (result or {{}}).get({json.dumps(model.unwrap_field)}),",
                f"                {_literal(model.unwrap_default)},",
                "            ),",
                "        )",
            )
        )
    elif model.flavor == "list":
        lines.extend(_execute_lines(model, "result = await "))
        lines.extend(
            (
                "        return cast(",
                f"            {json.dumps(model.return_type)},",
                "            or_default(result, []),",
                "        )",
            )
        )
    else:
        lines.extend(_cast_execute_lines(model))
    lines.append("")
    return lines


def emit_async(models: list[MethodModel]) -> str:
    lines = [
        HEADER.rstrip(),
        "# ruff: noqa: ASYNC109, F403, F405",
        "from __future__ import annotations",
        "",
        "from collections.abc import Sequence",
        "from typing import TYPE_CHECKING, Any, cast",
        "",
        "from ._codec import decode_base64, drop_unset, or_default, write_binary_file",
        "from ._unset import UNSET, UnsetType",
        "from .types import *",
        "",
        "if TYPE_CHECKING:",
        "    from .element_handle import ElementHandle",
        "    from .page import Page",
        "",
        "",
        "class PageGenerated:",
        "    async def _execute(",
        "        self,",
        "        mutation_name: str,",
        "        args: dict[str, object] | None,",
        "        response_type: str,",
        "        *,",
        "        timeout: float | None = None,",
        "        opt_in: Sequence[str] = (),",
        "    ) -> Any:",
        "        raise NotImplementedError",
        "",
    ]
    for model in models:
        lines.extend(_async_method(model))
    return "\n".join(lines)


def _sync_arguments(model: MethodModel) -> tuple[str, ...]:
    positional = [p.py_name for p in model.params if p.positional]
    keyword = [f"{p.py_name}={p.py_name}" for p in model.params if not p.positional]
    return (*positional, *keyword)


def _sync_result_lines(model: MethodModel) -> list[str]:
    arguments = (json.dumps(model.py_name), *_sync_arguments(model))
    return_type = json.dumps(model.return_type)
    lines = [
        "        return cast(",
        f"            {return_type},",
        "            self._invoke(",
    ]
    lines.extend(f"                {argument}," for argument in arguments)
    lines.extend(("            ),", "        )"))
    return lines


def emit_sync(models: list[MethodModel]) -> str:
    lines = [
        HEADER.rstrip(),
        "# ruff: noqa: F403, F405",
        "from __future__ import annotations",
        "",
        "from typing import TYPE_CHECKING, Any, cast",
        "",
        "from .._unset import UNSET, UnsetType",
        "from ..types import *",
        "",
        "if TYPE_CHECKING:",
        "    from .element_handle import ElementHandle",
        "",
        "",
        "class PageGenerated:",
        "    if TYPE_CHECKING:",
        "",
        "        def _invoke(",
        "            self,",
        "            method_name: str,",
        "            *args: object,",
        "            **kwargs: object,",
        "        ) -> Any: ...",
        "",
    ]
    for model in models:
        lines.append(f"    def {model.py_name}(")
        lines.extend(_signature_lines(model, "        "))
        lines.append(f"    ) -> {model.return_type}:")
        if docstring := model.doc:
            lines.append(f"        {json.dumps(docstring, ensure_ascii=False)}")
        lines.extend(_sync_result_lines(model))
        lines.append("")
    return "\n".join(lines)
