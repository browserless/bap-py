import tomllib
from hashlib import sha256
from pathlib import Path

from graphql import parse

import browserless_bap as bap


def test_version_is_available() -> None:
    assert bap.__version__ == "0.2.0"


def test_vendored_schema_is_locked_but_not_public() -> None:
    assert not hasattr(bap, "schema_source")
    schema = (
        Path(__file__).resolve().parents[1] / "src/browserless_bap/mutations.graphql"
    ).read_bytes()
    parse(schema.decode("utf-8"))
    lock_path = Path(__file__).resolve().parents[1] / "schema.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["line_count"] == len(schema.splitlines())
    assert lock["sha256"] == sha256(schema).hexdigest()
