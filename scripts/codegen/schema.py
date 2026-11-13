"""Parsed and validated BrowserQL schema index."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

from graphql import parse
from graphql.language import (
    EnumTypeDefinitionNode,
    FieldDefinitionNode,
    InputObjectTypeDefinitionNode,
    ListTypeNode,
    NamedTypeNode,
    NonNullTypeNode,
    ObjectTypeDefinitionNode,
    ScalarTypeDefinitionNode,
    TypeNode,
)

from .config.client_only import CLIENT_ONLY_PARAMS
from .config.methods import (
    METHOD_SPECS,
    NULLABLE_RETURNS,
    PAGE_EXCLUDED,
    PAGE_MANUAL,
    POSITIONAL_ARGS,
    SHARED_OPTIONS,
    options_name,
)
from .config.schema_map import (
    ENUM_NAME_OVERRIDES,
    EXCLUDED_MUTATIONS,
    EXCLUDED_TYPES,
    OPTIONAL_FIELDS,
    RESPONSE_FIELD_TYPE_OVERRIDES,
    RESPONSE_RENAME_EXCLUDE,
    RESPONSE_TYPE_OVERRIDES,
    SCALAR_MAP,
    SUBSCRIPTION_OMIT_FIELDS,
)


def named_type(node: TypeNode) -> str:
    while isinstance(node, (NonNullTypeNode, ListTypeNode)):
        node = node.type
    assert isinstance(node, NamedTypeNode)
    return node.name.value


def is_required(node: TypeNode) -> bool:
    return isinstance(node, NonNullTypeNode)


def is_list(node: TypeNode) -> bool:
    if isinstance(node, NonNullTypeNode):
        node = node.type
    return isinstance(node, ListTypeNode)


def render_graphql_type(node: TypeNode) -> str:
    if isinstance(node, NonNullTypeNode):
        return f"{render_graphql_type(node.type)}!"
    if isinstance(node, ListTypeNode):
        return f"[{render_graphql_type(node.type)}]"
    assert isinstance(node, NamedTypeNode)
    return node.name.value


@dataclass
class Schema:
    source: str
    enums: dict[str, EnumTypeDefinitionNode]
    inputs: dict[str, InputObjectTypeDefinitionNode]
    objects: dict[str, ObjectTypeDefinitionNode]
    scalars: set[str]
    mutation: ObjectTypeDefinitionNode
    subscription: ObjectTypeDefinitionNode | None
    response_overrides: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Schema:
        source = path.read_text(encoding="utf-8")
        document = parse(source)
        enums: dict[str, EnumTypeDefinitionNode] = {}
        inputs: dict[str, InputObjectTypeDefinitionNode] = {}
        objects: dict[str, ObjectTypeDefinitionNode] = {}
        scalars: set[str] = set()
        mutation = None
        subscription = None
        for definition in document.definitions:
            name_node = getattr(definition, "name", None)
            if name_node is None:
                continue
            name = name_node.value
            if isinstance(definition, EnumTypeDefinitionNode):
                if name not in EXCLUDED_TYPES:
                    enums[name] = definition
            elif isinstance(definition, InputObjectTypeDefinitionNode):
                inputs[name] = definition
            elif isinstance(definition, ObjectTypeDefinitionNode):
                objects[name] = definition
                if name == "Mutation":
                    mutation = definition
                elif name == "Subscription":
                    subscription = definition
            elif isinstance(definition, ScalarTypeDefinitionNode):
                scalars.add(name)
        if mutation is None:
            raise ValueError("Schema has no Mutation type")

        overrides = dict(RESPONSE_TYPE_OVERRIDES)
        mutation_names = {field.name.value for field in mutation.fields or ()}
        for object_name in objects:
            if (
                object_name not in RESPONSE_RENAME_EXCLUDE
                and object_name
                and object_name[0].lower() + object_name[1:] in mutation_names
            ):
                overrides.setdefault(object_name, f"{object_name}Response")

        result = cls(
            source=source,
            enums=enums,
            inputs=inputs,
            objects=objects,
            scalars=scalars,
            mutation=mutation,
            subscription=subscription,
            response_overrides=overrides,
        )
        result._validate_config()
        return result

    @property
    def mutation_fields(self) -> dict[str, FieldDefinitionNode]:
        return {field.name.value: field for field in self.mutation.fields or ()}

    @property
    def subscription_fields(self) -> dict[str, FieldDefinitionNode]:
        if self.subscription is None:
            return {}
        return {field.name.value: field for field in self.subscription.fields or ()}

    @property
    def response_objects(self) -> dict[str, ObjectTypeDefinitionNode]:
        return {
            name: node
            for name, node in self.objects.items()
            if name not in {"Query", "Mutation", "Subscription"}
            and name not in EXCLUDED_TYPES
        }

    def enum_name(self, graphql_name: str) -> str:
        return ENUM_NAME_OVERRIDES.get(graphql_name, graphql_name)

    def response_name(self, graphql_name: str) -> str:
        return self.response_overrides.get(graphql_name, graphql_name)

    def python_type(self, node: TypeNode, *, response: bool = False) -> str:
        if isinstance(node, NonNullTypeNode):
            return self.python_type(node.type, response=response)
        if isinstance(node, ListTypeNode):
            return f"list[{self.python_type(node.type, response=response)}]"
        assert isinstance(node, NamedTypeNode)
        name = node.name.value
        if name in SCALAR_MAP:
            return SCALAR_MAP[name]
        if name in self.enums:
            return self.enum_name(name)
        if name in self.inputs:
            return name
        if name in self.objects:
            return self.response_name(name) if response else name
        return "object"

    def positionals_for(self, field: FieldDefinitionNode) -> tuple[str, ...]:
        mutation = field.name.value
        if mutation in POSITIONAL_ARGS:
            return tuple(POSITIONAL_ARGS[mutation])
        return tuple(
            arg.name.value
            for arg in field.arguments or ()
            if is_required(arg.type)
            and named_type(arg.type) in {*SCALAR_MAP, *self.enums}
        )

    def response_selection(
        self,
        graphql_type: str,
        *,
        omit: Iterable[str] = (),
        _seen: frozenset[str] = frozenset(),
    ) -> str:
        node = self.objects.get(graphql_type)
        if node is None:
            return ""
        excluded = set(omit)
        for group in OPTIONAL_FIELDS.get(graphql_type, {}).values():
            excluded.update(group)
        parts: list[str] = []
        for field in node.fields or ():
            name = field.name.value
            if name in excluded or field.arguments:
                continue
            child = named_type(field.type)
            if child in self.objects:
                if child in _seen:
                    continue
                nested = self.response_selection(child, _seen=_seen | {child})
                if nested:
                    parts.append(f"{name} {{ {nested} }}")
                continue
            parts.append(name)
        return " ".join(parts)

    def _validate_config(self) -> None:
        fields = self.mutation_fields
        table_sets: tuple[tuple[str, Collection[str]], ...] = (
            ("POSITIONAL_ARGS", POSITIONAL_ARGS),
            ("METHOD_SPECS", METHOD_SPECS),
            ("PAGE_MANUAL", PAGE_MANUAL),
            ("PAGE_EXCLUDED", PAGE_EXCLUDED),
            ("NULLABLE_RETURNS", NULLABLE_RETURNS),
            ("EXCLUDED_MUTATIONS", EXCLUDED_MUTATIONS),
            ("SHARED_OPTIONS", SHARED_OPTIONS),
        )
        errors: list[str] = []
        for table_name, table in table_sets:
            for key in table:
                if key not in fields:
                    errors.append(f"{table_name} contains unknown mutation {key!r}")
        for mutation, args in POSITIONAL_ARGS.items():
            field = fields.get(mutation)
            actual = (
                {arg.name.value for arg in field.arguments or ()}
                if field is not None
                else set()
            )
            for arg in args:
                if arg not in actual:
                    errors.append(
                        f"POSITIONAL_ARGS[{mutation!r}] contains unknown "
                        f"argument {arg!r}"
                    )
        for mutation, specs in METHOD_SPECS.items():
            field = fields.get(mutation)
            actual = (
                {arg.name.value for arg in field.arguments or ()}
                if field is not None
                else set()
            )
            for spec in specs:
                for arg in spec.positional:
                    if arg not in actual:
                        errors.append(
                            f"METHOD_SPECS[{mutation!r}] contains unknown "
                            f"positional {arg!r}"
                        )
        for event in SUBSCRIPTION_OMIT_FIELDS:
            if event not in self.subscription_fields:
                errors.append(
                    f"SUBSCRIPTION_OMIT_FIELDS contains unknown event {event!r}"
                )
        for type_name, groups in OPTIONAL_FIELDS.items():
            node = self.objects.get(type_name)
            if node is None:
                errors.append(f"OPTIONAL_FIELDS contains unknown type {type_name!r}")
                continue
            actual_fields = {field.name.value for field in node.fields or ()}
            for group in groups.values():
                for name in group:
                    if name not in actual_fields:
                        errors.append(
                            f"OPTIONAL_FIELDS[{type_name!r}] contains unknown "
                            f"field {name!r}"
                        )
        for field in fields.values():
            groups = OPTIONAL_FIELDS.get(named_type(field.type), {})
            for client in CLIENT_ONLY_PARAMS.get(options_name(field.name.value), ()):
                if client.opt_in is not None and client.opt_in not in groups:
                    errors.append(
                        f"CLIENT_ONLY_PARAMS[{options_name(field.name.value)!r}] "
                        f"contains unknown optional field group {client.opt_in!r}"
                    )
        for type_name, field_name in RESPONSE_FIELD_TYPE_OVERRIDES:
            node = self.objects.get(type_name)
            if node is None or field_name not in {
                field.name.value for field in node.fields or ()
            }:
                errors.append(
                    "RESPONSE_FIELD_TYPE_OVERRIDES contains unknown field "
                    f"{type_name}.{field_name}"
                )
        builtin_scalars = {"String", "Int", "Float", "Boolean", "ID"}
        for scalar in self.scalars - builtin_scalars:
            if scalar not in SCALAR_MAP:
                errors.append(f"unmapped custom scalar {scalar!r}")
        option_names = {options_name(field.name.value) for field in fields.values()}
        for option_name in CLIENT_ONLY_PARAMS:
            if option_name not in option_names:
                errors.append(
                    f"CLIENT_ONLY_PARAMS contains unknown options type {option_name!r}"
                )
        if errors:
            raise ValueError("Invalid codegen configuration:\n- " + "\n- ".join(errors))
