"""GraphQL-to-Python type configuration.

Keys deliberately match the bap-ts generator so parity can be audited
mechanically.
"""

ENUM_NAME_OVERRIDES = {
    "CountryType": "CountryCode",
    "CaptchaTypes": "CaptchaType",
    "OperatorTypes": "OperatorType",
}

RESPONSE_TYPE_OVERRIDES = {"Headers": "RequestHeader"}
RESPONSE_RENAME_EXCLUDE = {"WaitForFunction", "WaitForEvent"}

SCALAR_MAP = {
    "String": "str",
    "Int": "int",
    "Float": "float",
    "Boolean": "bool",
    "FloatOrString": "float | str",
    "StringOrArray": "str | list[str]",
    "StringOrInstructions": "str | LiveURLInstructions",
}

EXCLUDED_TYPES = {"VerifyResponse", "VerifyTypes"}
EXCLUDED_MUTATIONS = {
    "if",
    "ifnot",
    "verify",
    "title",
    "url",
    "stopSessionRecording",
}

SUBSCRIPTION_OMIT_FIELDS = {"response": {"body"}}
UNSUPPORTED_FIELDS = {
    "HTTPResponse": {
        "fields": {"ip", "port"},
        "variant": "HTTPResponseWithRemoteMetadata",
    },
    "ResponseResponse": {
        "fields": {"base64Encoded"},
        "variant": "ResponseResponseWithBodyEncoding",
    },
}
