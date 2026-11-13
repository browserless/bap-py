import builtins

from browserless_bap.errors import (
    BAPError,
    BrowserQLError,
    ConnectionError,
    SchemaMismatchError,
    TimeoutError,
    ValueError,
)


def test_error_codes_and_context() -> None:
    bql = BrowserQLError([{"message": "first"}, {"message": "second"}])
    assert str(bql) == "first; second"
    assert bql.code == "BQL"
    assert bql.errors == [{"message": "first"}, {"message": "second"}]

    connection = ConnectionError("closed")
    assert connection.code == "CONNECTION"

    timeout = TimeoutError("mutation { goto }", 250)
    assert timeout.code == "TIMEOUT"
    assert timeout.operation == "mutation { goto }"
    assert timeout.timeout_ms == 250

    mismatch = SchemaMismatchError("stale generated output")
    assert mismatch.code == "CLIENT"


def test_bap_value_error_is_native_value_error_too() -> None:
    error = ValueError("invalid")
    assert isinstance(error, BAPError)
    assert isinstance(error, builtins.ValueError)
    assert error.code == "CLIENT"


def test_transport_errors_are_native_errors_too() -> None:
    assert isinstance(ConnectionError("closed"), builtins.ConnectionError)
    assert isinstance(
        TimeoutError("mutation { goto }", 250),
        builtins.TimeoutError,
    )


def test_custom_bap_error_has_safe_default_code() -> None:
    class CustomError(BAPError):
        pass

    assert CustomError("custom").code == "CLIENT"


def test_browserql_error_normalises_entries() -> None:
    error = BrowserQLError(["boom", 42, None, {"message": "ok"}])
    assert error.errors == [
        {"message": "boom"},
        {"message": "42"},
        {"message": "None"},
        {"message": "ok"},
    ]
    assert str(error) == "boom; 42; None; ok"
