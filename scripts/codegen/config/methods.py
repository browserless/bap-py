"""Page-method configuration ported from bap-ts."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MethodSpec:
    method: str
    positional: tuple[str, ...] = ()
    inject: dict[str, object] = field(default_factory=dict)
    options: bool = True
    unwrap: bool | tuple[str, str, object] = False
    wrap: str | None = None


POSITIONAL_ARGS = {
    "viewport": (),
    "evaluate": ("content",),
    "solveImageCaptcha": (),
    "hover": ("selector",),
}

PAGE_EXCLUDED = {"if", "ifnot", "verify"}
PAGE_MANUAL = {
    "select",
    "setExtraHTTPHeaders",
    "evaluate",
    "waitForFunction",
    "waitForRequest",
    "waitForResponse",
    "waitForTimeout",
    "addScriptTag",
    "addStyleTag",
}
NULLABLE_RETURNS = {
    "goto",
    "back",
    "forward",
    "reload",
    "content",
    "authenticate",
}
SHARED_OPTIONS = {
    "back": "NavigationOptions",
    "forward": "NavigationOptions",
    "reload": "NavigationOptions",
    "querySelectorAll": "QuerySelectorOptions",
}

OPTIONS_NAME_OVERRIDES = {
    "goto": "GotoOptions",
    "back": "NavigationOptions",
    "forward": "NavigationOptions",
    "reload": "NavigationOptions",
    "content": "SetContentOptions",
    "click": "ClickOptions",
    "hover": "HoverOptions",
    "scroll": "ScrollOptions",
    "type": "TypeOptions",
    "checkbox": "CheckboxOptions",
    "select": "SelectOptions",
    "screenshot": "ScreenshotOptions",
    "pdf": "PDFOptions",
    "html": "HTMLOptions",
    "text": "TextOptions",
    "querySelector": "QuerySelectorOptions",
    "querySelectorAll": "QuerySelectorOptions",
    "mapSelector": "MapSelectorOptions",
    "waitForSelector": "WaitForSelectorOptions",
    "waitForNavigation": "WaitForNavigationOptions",
    "waitForRequest": "WaitForRequestOptions",
    "waitForResponse": "WaitForResponseOptions",
    "waitForTimeout": "WaitForTimeoutOptions",
    "viewport": "ViewportOptions",
    "cookies": "SetCookieOptions",
    "setExtraHTTPHeaders": "SetExtraHTTPHeadersOptions",
    "evaluate": "EvaluateOptions",
    "request": "RequestFilterOptions",
    "response": "ResponseFilterOptions",
    "reject": "RejectOptions",
    "reconnect": "ReconnectOptions",
    "liveURL": "LiveURLOptions",
    "preferences": "PreferencesOptions",
    "proxy": "ProxyOptions",
    "solve": "SolveOptions",
    "solveImageCaptcha": "SolveImageCaptchaOptions",
    "javaScriptEnabled": "JavaScriptEnabledOptions",
    "switchToWindow": "SwitchToWindowOptions",
}


def options_name(mutation: str) -> str:
    return OPTIONS_NAME_OVERRIDES.get(
        mutation, f"{mutation[0].upper()}{mutation[1:]}Options"
    )


METHOD_SPECS = {
    "closeLiveURL": (MethodSpec("closeLiveURL", ("liveURLId",), options=False),),
    "goto": (MethodSpec("goto", ("url",)),),
    "back": (MethodSpec("goBack"),),
    "forward": (MethodSpec("goForward"),),
    "reload": (MethodSpec("reload"),),
    "content": (MethodSpec("setContent", ("html",)),),
    "click": (MethodSpec("click", ("selector",)),),
    "type": (MethodSpec("type", ("selector", "text")),),
    "checkbox": (
        MethodSpec("check", ("selector",), {"checked": True}),
        MethodSpec("uncheck", ("selector",), {"checked": False}),
    ),
    "loadSecret": (MethodSpec("loadSecret", ("ref",)),),
    "html": (
        MethodSpec("html"),
        MethodSpec("content", options=False, unwrap=True),
    ),
    "text": (
        MethodSpec("text"),
        MethodSpec("$eval", ("selector",), options=False, unwrap=True),
    ),
    "hover": (MethodSpec("hover", ("selector",)),),
    "title": (MethodSpec("title", options=False, unwrap=True),),
    "url": (MethodSpec("url", options=False, unwrap=True),),
    "cookies": (MethodSpec("cookies", options=False, unwrap=True),),
    "screenshot": (MethodSpec("screenshot"),),
    "pdf": (MethodSpec("pdf"),),
    "querySelector": (MethodSpec("$", ("selector",), wrap="element"),),
    "querySelectorAll": (MethodSpec("$$", ("selector",), wrap="elementList"),),
    "mapSelector": (
        MethodSpec("mapSelector", ("selector",)),
        MethodSpec("$$eval", ("selector",)),
    ),
    "request": (MethodSpec("request"),),
    "response": (MethodSpec("response"),),
    "userAgent": (MethodSpec("setUserAgent", ("userAgent",), options=False),),
    "viewport": (MethodSpec("setViewport"),),
    "javaScriptEnabled": (
        MethodSpec("setJavaScriptEnabled", ("enabled",), options=False),
    ),
    "emulateMediaType": (MethodSpec("emulateMediaType", ("type",), options=False),),
    "authenticate": (MethodSpec("authenticate", ("username", "password")),),
    "waitForSelector": (MethodSpec("waitForSelector", ("selector",)),),
    "waitForFunction": (MethodSpec("waitForFunction", ("fn",)),),
    "waitForEvent": (MethodSpec("waitForEvent", ("event",)),),
    "watchEvent": (MethodSpec("watchEvent", ("event",), options=False),),
    "stopSessionRecording": (MethodSpec("stopSessionRecording", options=False),),
}

PLAYWRIGHT_METHODS = {
    "goto",
    "go_back",
    "go_forward",
    "reload",
    "set_content",
    "wait_for_navigation",
    "click",
    "type",
    "select_option",
    "hover",
    "title",
    "url",
    "content",
    "screenshot",
    "pdf",
    "query_selector",
    "query_selector_all",
    "wait_for_selector",
    "wait_for_function",
    "evaluate",
    "set_user_agent",
    "set_viewport_size",
    "add_cookies",
    "cookies",
    "set_extra_http_headers",
    "emulate_media",
    "add_script_tag",
    "add_style_tag",
    "wait_for_timeout",
    "wait_for_request",
    "wait_for_response",
    "close",
}

HANDWRITTEN_METHODS = (
    ("wait_for_live_complete", "liveComplete", "LiveURLCompleteEvent"),
    ("select_option", "select", "SelectResponse"),
    ("add_cookies", "cookies", "CookieResponse"),
    ("set_extra_http_headers", "setExtraHTTPHeaders", "HTTPHeadersResponse"),
    ("evaluate", "evaluate", "str | None"),
    ("wait_for_function", "waitForFunction", "WaitForFunction"),
    ("wait_for_request", "waitForRequest", "WaitForRequestResponse"),
    ("wait_for_response", "waitForResponse", "WaitForResponseResponse"),
    ("wait_for_timeout", "waitForTimeout", "None"),
    ("add_script_tag", "addScriptTag", "AddScriptTagResponse"),
    ("add_style_tag", "addStyleTag", "AddStyleTagResponse"),
    ("send", "—", "T"),
    ("close", "—", "None"),
)
