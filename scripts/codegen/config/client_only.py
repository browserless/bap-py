"""Client-only parameters and option types."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientParam:
    name: str
    annotation: str
    transport_timeout: bool = False
    opt_in: str | None = None


CLIENT_ONLY_PARAMS = {
    "GotoOptions": (
        ClientParam("remote_response_metadata", "bool", opt_in="remoteMetadata"),
    ),
    "ResponseFilterOptions": (
        ClientParam("body", "bool", opt_in="body"),
        ClientParam("body_encoding", "bool", opt_in="bodyEncoding"),
    ),
    "QuerySelectorOptions": (ClientParam("html", "bool", opt_in="html"),),
    "ScreenshotOptions": (ClientParam("path", "str"),),
    "PDFOptions": (ClientParam("path", "str"),),
    "AddScriptTagOptions": (ClientParam("path", "str"),),
    "AddStyleTagOptions": (ClientParam("path", "str"),),
    "WaitForFunctionOptions": (ClientParam("complete_on_promise_resolution", "bool"),),
    "WaitForResponseOptions": (
        ClientParam("timeout", "float", transport_timeout=True),
    ),
}

CLIENT_ONLY_TYPES = {
    "LiveURLInstructions": {
        "layout": "InstructionsLayout",
        "format": "InstructionsFormat",
        "title": "str",
        "summary": "str",
        "steps": "list[str]",
        "currentStep": "int",
    },
    "SendOptions": {
        "variables": "dict[str, object]",
        "timeout": "float",
    },
    "ConnectOptions": {
        "browser_ws_endpoint": "str",
        "token": "str",
        "timeout": "float",
        "connect_timeout": "float",
        "transport": "object",
    },
}
