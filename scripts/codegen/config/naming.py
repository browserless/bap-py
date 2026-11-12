"""Canonical TypeScript-to-Python public naming map."""

import keyword
import re


def camel_to_snake(value: str) -> str:
    value = value.replace("$", "query_selector")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = value.replace("-", "_").lower()
    return f"{value}_" if keyword.iskeyword(value) else value


METHOD_NAME_OVERRIDES = {
    "$": "query_selector",
    "$$": "query_selector_all",
    "$eval": "eval_on_selector",
    "$$eval": "eval_on_selector_all",
    "setViewport": "set_viewport_size",
    "emulateMediaType": "emulate_media",
    "select": "select_option",
    "setCookie": "add_cookies",
}

PARAM_NAME_OVERRIDES = {
    "userAgent": "user_agent",
    "waitUntil": "wait_until",
    "waitUntilAll": "wait_until_all",
    "deviceScaleFactor": "device_scale_factor",
    "hasTouch": "has_touch",
    "referrerPolicy": "referrer_policy",
    "idleTime": "idle_time",
    "base64Body": "base64_body",
    "contentType": "content_type",
}


def method_name(ts_name: str) -> str:
    return METHOD_NAME_OVERRIDES.get(ts_name, camel_to_snake(ts_name))


def param_name(gql_name: str) -> str:
    return PARAM_NAME_OVERRIDES.get(gql_name, camel_to_snake(gql_name))
