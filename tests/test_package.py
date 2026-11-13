import json
import tomllib
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from graphql import parse

import browserless_bap as bap


def test_version_matches_metadata_and_release_manifest() -> None:
    # release-please bumps _version.py and the manifest together in its release PR.
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / ".release-please-manifest.json").read_text())
    assert bap.__version__ == version("browserless-bap")
    assert manifest["."] == bap.__version__


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
