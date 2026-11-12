from __future__ import annotations

# Template strings intentionally contain complete generated signatures.
# ruff: noqa: E501
from .config.schema_map import SUBSCRIPTION_OMIT_FIELDS
from .schema import Schema, named_type, render_graphql_type
from .writer import HEADER


def subscription_specs(schema: Schema) -> dict[str, dict[str, object]]:
    specs: dict[str, dict[str, object]] = {}
    for event, field in schema.subscription_fields.items():
        gql_type = named_type(field.type)
        specs[event] = {
            "response_type": schema.response_name(gql_type),
            "fields": schema.response_selection(
                gql_type, omit=SUBSCRIPTION_OMIT_FIELDS.get(event, ())
            ),
            "arg_types": {
                arg.name.value: render_graphql_type(arg.type)
                for arg in field.arguments or ()
            },
        }
    return specs


def emit_subscriptions(schema: Schema) -> str:
    import json

    return "\n".join(
        (
            HEADER.rstrip(),
            "from __future__ import annotations",
            "",
            "from typing import TypedDict",
            "",
            "",
            "class SubscriptionSpec(TypedDict):",
            "    response_type: str",
            "    fields: str",
            "    arg_types: dict[str, str]",
            "",
            "",
            "# fmt: off",
            f"SUBSCRIPTIONS: dict[str, SubscriptionSpec] = {json.dumps(subscription_specs(schema), sort_keys=True, indent=4)}",
            "# fmt: on",
            "",
        )
    )


def emit_types(schema: Schema) -> str:
    entries = [
        (event, schema.response_name(named_type(field.type)))
        for event, field in schema.subscription_fields.items()
    ]
    import json

    event_literals = ", ".join(
        json.dumps(event) for event in (*schema.subscription_fields, "error", "message")
    )
    lines = [
        HEADER.rstrip(),
        "# ruff: noqa: F403, F405",
        "from __future__ import annotations",
        "",
        "from collections.abc import Callable",
        "from typing import Any, Literal, Self, TypedDict, overload",
        "",
        "from .responses import *",
        "",
        (
            f"EventName = Literal[{event_literals}]"
            if len(f"EventName = Literal[{event_literals}]") <= 88
            else f"EventName = Literal[\n    {event_literals}\n]"
        ),
        "Listener = Callable[[Any], Any]",
        "",
        "",
        "class PageEventMap(TypedDict):",
    ]
    for event, response in entries:
        lines.append(f"    {event}: {response}")
    lines.extend(
        (
            "    error: Exception",
            "    message: str",
            "",
            "",
            "class PageEventsMixin:",
        )
    )
    for method in ("on", "once", "off"):
        for event, response in entries:
            lines.extend(
                (
                    "    @overload",
                    f"    def {method}(",
                    *(
                        (
                            f"        self, event: Literal[{json.dumps(event)}], listener: Callable[[{response}], Any]",
                        )
                        if len(
                            f"        self, event: Literal[{json.dumps(event)}], listener: Callable[[{response}], Any]"
                        )
                        <= 88
                        else (
                            "        self,",
                            f"        event: Literal[{json.dumps(event)}],",
                            f"        listener: Callable[[{response}], Any],",
                        )
                    ),
                    "    ) -> Self: ...",
                )
            )
        lines.extend(
            (
                "    @overload",
                f"    def {method}(",
                '        self, event: Literal["error"], listener: Callable[[Exception], Any]',
                "    ) -> Self: ...",
                "    @overload",
                *(
                    (
                        f'    def {method}(self, event: Literal["message"], listener: Callable[[str], Any]) -> Self: ...',
                    )
                    if method == "on"
                    else (
                        f"    def {method}(",
                        '        self, event: Literal["message"], listener: Callable[[str], Any]',
                        "    ) -> Self: ...",
                    )
                ),
                f"    def {method}(self, event: EventName, listener: Listener) -> Self:",
                f"        self._{method}(event, listener)",
                "        return self",
                "",
            )
        )
    lines.extend(
        (
            "    def _on(self, event: EventName, listener: Listener) -> None:",
            "        raise NotImplementedError",
            "",
            "    def _once(self, event: EventName, listener: Listener) -> None:",
            "        raise NotImplementedError",
            "",
            "    def _off(self, event: EventName, listener: Listener) -> None:",
            "        raise NotImplementedError",
            "",
        )
    )
    return "\n".join(lines)
