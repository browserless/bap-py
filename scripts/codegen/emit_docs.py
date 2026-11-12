"""README/llms tables and optional Docusaurus-compatible reference output."""

from __future__ import annotations

import ast
from pathlib import Path

from griffe import (
    Alias,
    AliasResolutionError,
    Attribute,
    Class,
    CyclicAliasError,
    Function,
    GriffeLoader,
    Module,
)

from .config.methods import HANDWRITTEN_METHODS, PLAYWRIGHT_METHODS
from .model import MethodModel
from .writer import write_if_changed


def method_rows(models: list[MethodModel]) -> list[tuple[str, str, str]]:
    rows = [(model.py_name, model.mutation, model.return_type) for model in models]
    rows.extend(HANDWRITTEN_METHODS)
    return sorted(rows)


def readme_table(models: list[MethodModel]) -> str:
    lines = [
        "| Method | Source mutation | Returns | Playwright-named |",
        "| ------ | --------------- | ------- | ---------------- |",
    ]
    for method, mutation, returns in method_rows(models):
        returns = returns.replace("|", "\\|")
        mark = "✅" if method in PLAYWRIGHT_METHODS else "—"
        lines.append(f"| `{method}` | `{mutation}` | `{returns}` | {mark} |")
    return "\n".join(lines)


def llms_method_list(models: list[MethodModel]) -> str:
    groups = ", ".join(f"`{name}`" for name, _, _ in method_rows(models))
    return f"Generated Page methods: {groups}"


def _summary(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().split("\n\n", 1)[0]


def _public_signature(identifier: str, name: str, member: Function) -> str:
    if name == "page" and identifier == "async-browser":
        return "page() -> AsyncContextManager[Page]"
    if name == "page" and identifier == "sync-browser":
        return "page() -> ContextManager[Page]"
    return str(member.signature())


def _usage_example(identifier: str, name: str) -> tuple[str, ...]:
    if name != "page":
        return ()
    if identifier == "async-browser":
        return (
            "```python",
            "async with browser.page() as page:",
            '    await page.goto("https://example.com")',
            "```",
            "",
        )
    if identifier == "sync-browser":
        return (
            "```python",
            "with browser.page() as page:",
            '    page.goto("https://example.com")',
            "```",
            "",
        )
    return ()


def _class_page(identifier: str, title: str, class_: Class) -> str:
    lines = ["---", f"id: {identifier}", f"title: {title}", "---", "", f"# {title}", ""]
    summary = _summary(class_.docstring.value if class_.docstring else None)
    if summary:
        lines.extend((summary, ""))
    for name, member in sorted(class_.all_members.items()):
        if name.startswith("_"):
            continue
        if isinstance(member, Alias):
            try:
                member = member.final_target
            except (AliasResolutionError, CyclicAliasError):
                continue
        if isinstance(member, Attribute) and "property" in member.labels:
            lines.extend(
                (
                    f"## `{name}`",
                    "",
                    f"Type: `{_attribute_type(member)}`",
                    "",
                )
            )
            continue
        if not isinstance(member, Function):
            continue
        lines.extend(
            (
                f"## `{name}`",
                "",
                "```python",
                _public_signature(identifier, name, member),
                "```",
                "",
            )
        )
        member_summary = _summary(member.docstring.value if member.docstring else None)
        if member_summary:
            lines.extend((member_summary, ""))
        lines.extend(_usage_example(identifier, name))
    return "\n".join(lines)


def _attribute_type(member: Attribute) -> str:
    expression = member.annotation or member.value
    if expression is None:
        raise ValueError(f"Public attribute {member.path} has no type expression")
    return str(expression)


def _table_type(value: object) -> str:
    return str(value).replace("|", "\\|")


def _functional_typed_dict_fields(member: Attribute) -> list[tuple[str, str]] | None:
    value = member.value
    if value is None:
        return None
    try:
        expression = ast.parse(str(value), mode="eval").body
    except SyntaxError:
        return None
    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != "TypedDict"
        or len(expression.args) < 2
        or not isinstance(expression.args[1], ast.Dict)
    ):
        return None
    fields: list[tuple[str, str]] = []
    for key, field_type in zip(
        expression.args[1].keys, expression.args[1].values, strict=True
    ):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if isinstance(field_type, ast.Constant) and isinstance(field_type.value, str):
            rendered_type = field_type.value
        else:
            rendered_type = ast.unparse(field_type)
        fields.append((key.value, rendered_type))
    return fields


def _typed_module_page(identifier: str, title: str, module: Module) -> str:
    lines = ["---", f"id: {identifier}", f"title: {title}", "---", "", f"# {title}", ""]
    for name, member in sorted(module.members.items()):
        if name.startswith("_") or member.is_imported:
            continue
        if isinstance(member, Class):
            lines.extend((f"## `{name}`", ""))
            summary = _summary(member.docstring.value if member.docstring else None)
            if summary:
                lines.extend((summary, ""))
            fields = [
                (field_name, field)
                for field_name, field in sorted(member.members.items())
                if not field_name.startswith("_") and isinstance(field, Attribute)
            ]
            if fields:
                lines.extend(
                    (
                        "| Field | Type |",
                        "| ----- | ---- |",
                        *(
                            "| "
                            f"`{field_name}` | "
                            f"`{_table_type(_attribute_type(field))}` |"
                            for field_name, field in fields
                        ),
                        "",
                    )
                )
            for method_name, method in sorted(member.members.items()):
                if method_name.startswith("_") or not isinstance(method, Function):
                    continue
                lines.extend(
                    (
                        f"### `{method_name}`",
                        "",
                        "```python",
                        str(method.signature()),
                        "```",
                        "",
                    )
                )
        elif isinstance(member, Attribute) and not name.endswith("_VALUES"):
            lines.extend((f"## `{name}`", ""))
            typed_dict_fields = _functional_typed_dict_fields(member)
            if typed_dict_fields is None:
                lines.extend((f"Type: `{_attribute_type(member)}`", ""))
            else:
                lines.extend(
                    (
                        "| Field | Type |",
                        "| ----- | ---- |",
                        *(
                            f"| `{field}` | `{_table_type(type_)}` |"
                            for field, type_ in typed_dict_fields
                        ),
                        "",
                    )
                )
    return "\n".join(lines)


def emit_reference(models: list[MethodModel], output: Path, root: Path) -> list[Path]:
    """Use Griffe plus MethodModel to emit Docusaurus-compatible public docs."""
    loader = GriffeLoader(search_paths=[root / "src"])
    targets = (
        (
            "async-browserless",
            "Async Browserless",
            "browserless_bap.browserless",
            "Browserless",
        ),
        ("async-browser", "Async Browser", "browserless_bap.browser", "Browser"),
        ("async-page", "Async Page", "browserless_bap.page", "Page"),
        (
            "async-element-handle",
            "Async ElementHandle",
            "browserless_bap.element_handle",
            "ElementHandle",
        ),
        (
            "sync-browserless",
            "Sync Browserless",
            "browserless_bap.sync_api.browserless",
            "Browserless",
        ),
        ("sync-browser", "Sync Browser", "browserless_bap.sync_api.browser", "Browser"),
        ("sync-page", "Sync Page", "browserless_bap.sync_api.page", "Page"),
        (
            "sync-element-handle",
            "Sync ElementHandle",
            "browserless_bap.sync_api.element_handle",
            "ElementHandle",
        ),
    )
    reference = output
    changed: list[Path] = []
    generated_names = {model.py_name for model in models}
    for identifier, title, module_name, class_name in targets:
        module = loader.load(module_name)
        class_ = module.members[class_name]
        if not isinstance(class_, Class):
            raise TypeError(f"{module_name}.{class_name} is not a class")
        if identifier in {"async-page", "sync-page"}:
            missing = generated_names - set(class_.all_members)
            if missing:
                raise ValueError(
                    f"{module_name}.{class_name} misses generated methods: "
                    + ", ".join(sorted(missing))
                )
        target = reference / f"{identifier}.mdx"
        if write_if_changed(target, _class_page(identifier, title, class_)):
            changed.append(target)

    error_module = loader.load("browserless_bap.errors")
    error_lines = [
        "---",
        "id: errors",
        "title: Errors",
        "---",
        "",
        "# Errors",
        "",
    ]
    for name, member in sorted(error_module.members.items()):
        if name.startswith("_") or not isinstance(member, Class):
            continue
        error_lines.extend((f"## `{name}`", ""))
        summary = _summary(member.docstring.value if member.docstring else None)
        if summary:
            error_lines.extend((summary, ""))
    errors_target = reference / "errors.mdx"
    if write_if_changed(errors_target, "\n".join(error_lines)):
        changed.append(errors_target)

    type_targets = (
        ("enums", "Enums", "browserless_bap.types.enums"),
        ("inputs", "Input types", "browserless_bap.types.inputs"),
        ("responses", "Response types", "browserless_bap.types.responses"),
        ("options", "Option types", "browserless_bap.types.options"),
        ("events", "Event types", "browserless_bap.types.events"),
    )
    for identifier, title, module_name in type_targets:
        module = loader.load(module_name)
        if not isinstance(module, Module):
            raise TypeError(f"{module_name} is not a module")
        target = reference / f"{identifier}.mdx"
        if write_if_changed(target, _typed_module_page(identifier, title, module)):
            changed.append(target)

    index = [
        "---",
        "id: index",
        "title: Python BAP API Reference",
        "---",
        "",
        "# Python BAP API Reference",
        "",
        "Generated async and sync API reference for `browserless-bap`.",
        "",
    ]
    index.extend(
        f"- [{title}](/sdk/bap-python/reference/{identifier})"
        for identifier, title, _, _ in targets
    )
    index.append("- [Errors](/sdk/bap-python/reference/errors)")
    index.extend(
        f"- [{title}](/sdk/bap-python/reference/{identifier})"
        for identifier, title, _ in type_targets
    )
    index_target = reference / "index.mdx"
    if write_if_changed(index_target, "\n".join(index)):
        changed.append(index_target)

    sidebar_groups = (
        (
            "Async API",
            (
                ("async-browserless", "Browserless"),
                ("async-browser", "Browser"),
                ("async-page", "Page"),
                ("async-element-handle", "ElementHandle"),
            ),
        ),
        (
            "Sync API",
            (
                ("sync-browserless", "Browserless"),
                ("sync-browser", "Browser"),
                ("sync-page", "Page"),
                ("sync-element-handle", "ElementHandle"),
            ),
        ),
        (
            "Types",
            (
                ("errors", "Errors"),
                ("enums", "Enums"),
                ("inputs", "Input types"),
                ("options", "Option types"),
                ("responses", "Response types"),
                ("events", "Event types"),
            ),
        ),
    )
    entries = ",\n  ".join(
        "\n".join(
            (
                "{",
                '    type: "category",',
                f'    label: "{group_label}",',
                "    collapsed: true,",
                "    items: [",
                *(
                    '      { type: "doc", id: "sdk/bap-python/reference/'
                    f'{identifier}", label: "{label}" }},'
                    for identifier, label in items
                ),
                "    ],",
                "  }",
            )
        )
        for group_label, items in sidebar_groups
    )
    sidebar_target = reference / "sidebar.cjs"
    if write_if_changed(
        sidebar_target,
        f"module.exports = [\n  {entries},\n];",
    ):
        changed.append(sidebar_target)
    return changed
