"""Method intermediate representation shared by async, sync, and docs emitters."""

from __future__ import annotations

from dataclasses import dataclass

from graphql.language import FieldDefinitionNode

from .config.client_only import CLIENT_ONLY_PARAMS
from .config.docs import METHOD_DOCSTRINGS, lead_prose
from .config.methods import (
    METHOD_SPECS,
    NULLABLE_RETURNS,
    PAGE_EXCLUDED,
    PAGE_MANUAL,
    MethodSpec,
    options_name,
)
from .config.naming import method_name, param_name
from .schema import Schema, is_list, is_required, named_type


@dataclass(frozen=True)
class Param:
    py_name: str
    gql_name: str | None
    annotation: str
    positional: bool
    required: bool
    transport_timeout: bool = False
    opt_in: str | None = None


@dataclass(frozen=True)
class MethodModel:
    py_name: str
    mutation: str
    response_type: str
    return_type: str
    params: tuple[Param, ...]
    inject: dict[str, object]
    flavor: str
    unwrap_field: str | None = None
    unwrap_default: object = None
    wrap: str | None = None
    doc: str | None = None

    @property
    def transport_timeout_param(self) -> str | None:
        for param in self.params:
            if param.transport_timeout or param.gql_name == "timeout":
                return param.py_name
        return None


def _derive_unwrap(schema: Schema, response_gql: str) -> tuple[str, str, object]:
    node = schema.objects[response_gql]
    candidates = [field for field in node.fields or () if field.name.value != "time"]
    if len(candidates) != 1:
        raise ValueError(
            f"Cannot derive unwrap for {response_gql}: expected one non-time field"
        )
    field = candidates[0]
    annotation = schema.python_type(field.type, response=True)
    if is_list(field.type):
        default: object = []
    elif annotation == "str":
        default = ""
    elif annotation == "bool":
        default = False
    elif annotation in {"float", "int"}:
        default = 0
    else:
        default = None
    return field.name.value, annotation, default


def _params(
    schema: Schema, field: FieldDefinitionNode, spec: MethodSpec
) -> tuple[Param, ...]:
    positional = set(spec.positional)
    params: list[Param] = []
    for arg in field.arguments or ():
        gql_name = arg.name.value
        if gql_name in spec.inject:
            continue
        is_positional = gql_name in positional
        if spec.options is False and not is_positional:
            continue
        params.append(
            Param(
                py_name=param_name(gql_name),
                gql_name=gql_name,
                annotation=schema.python_type(arg.type),
                positional=is_positional,
                required=is_required(arg.type),
            )
        )
    option_type = options_name(field.name.value)
    existing = {param.py_name for param in params}
    for client in CLIENT_ONLY_PARAMS.get(option_type, ()):
        if client.name in existing:
            params = [
                Param(
                    p.py_name,
                    None if p.py_name == client.name else p.gql_name,
                    p.annotation,
                    p.positional,
                    p.required,
                    client.transport_timeout
                    if p.py_name == client.name
                    else p.transport_timeout,
                    client.opt_in if p.py_name == client.name else p.opt_in,
                )
                for p in params
            ]
        else:
            params.append(
                Param(
                    py_name=client.name,
                    gql_name=None,
                    annotation=client.annotation,
                    positional=False,
                    required=False,
                    transport_timeout=client.transport_timeout,
                    opt_in=client.opt_in,
                )
            )
    positional_order = {name: index for index, name in enumerate(spec.positional)}
    positional_params = sorted(
        (param for param in params if param.positional),
        key=lambda param: positional_order[param.gql_name or ""],
    )
    keyword_params = [param for param in params if not param.positional]
    return tuple((*positional_params, *keyword_params))


def build_models(schema: Schema) -> list[MethodModel]:
    models: list[MethodModel] = []
    for field in schema.mutation.fields or ():
        mutation = field.name.value
        if mutation in PAGE_EXCLUDED or mutation in PAGE_MANUAL:
            continue
        response_gql = named_type(field.type)
        response_type = schema.response_name(response_gql)
        specs = METHOD_SPECS.get(mutation, (MethodSpec(mutation),))
        for spec in specs:
            flavor = "plain"
            unwrap_field = None
            unwrap_default = None
            return_type = response_type
            node = schema.objects.get(response_gql)
            buffer = bool(
                node
                and any(f.name.value == "base64" for f in node.fields or ())
                and response_type in {"ScreenshotResponse", "PDFResponse"}
            )
            if buffer:
                flavor = "buffer"
                return_type = "bytes"
            elif spec.wrap == "element":
                flavor = "element"
                return_type = "ElementHandle | None"
            elif spec.wrap == "elementList":
                flavor = "element_list"
                return_type = "list[ElementHandle]"
            elif spec.unwrap:
                flavor = "unwrap"
                if isinstance(spec.unwrap, tuple):
                    unwrap_field, return_type, unwrap_default = spec.unwrap
                else:
                    unwrap_field, return_type, unwrap_default = _derive_unwrap(
                        schema, response_gql
                    )
            elif is_list(field.type):
                flavor = "list"
                return_type = f"list[{response_type}]"
            elif mutation in NULLABLE_RETURNS:
                return_type = f"{response_type} | None"
            models.append(
                MethodModel(
                    py_name=method_name(spec.method),
                    mutation=mutation,
                    response_type=response_type,
                    return_type=return_type,
                    params=_params(schema, field, spec),
                    inject=spec.inject,
                    flavor=flavor,
                    unwrap_field=unwrap_field,
                    unwrap_default=unwrap_default,
                    wrap=spec.wrap,
                    doc=METHOD_DOCSTRINGS.get(method_name(spec.method))
                    or lead_prose(
                        field.description.value if field.description else None
                    ),
                )
            )
    return models
