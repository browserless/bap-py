import importlib.util
import sys
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_schema.py"
SPEC = importlib.util.spec_from_file_location("bap_sync_schema", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync_schema: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_schema
SPEC.loader.exec_module(sync_schema)


def candidate(
    *,
    source_repo: str,
    content: bytes,
) -> sync_schema.Candidate:
    return sync_schema.Candidate(
        source_repo=source_repo,
        source_path="mutations.graphql",
        source_commit="a" * 40,
        path=sync_schema.ROOT / "mutations.graphql",
        content=content,
    )


def test_auto_uses_bap_ts_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    bap_ts = candidate(source_repo="browserless/bap-ts", content=b"a\n")
    monkeypatch.setattr(sync_schema, "bap_ts_candidate", lambda: bap_ts)

    assert sync_schema.automatic_candidate() is bap_ts


def test_auto_reports_missing_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise FileNotFoundError("Schema source not found")

    monkeypatch.setattr(sync_schema, "bap_ts_candidate", missing)

    with pytest.raises(FileNotFoundError, match="--schema"):
        sync_schema.automatic_candidate()


def test_explicit_auto_mode_checks_without_siblings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = b"type Query { hello: String }\n"
    target = tmp_path / "mutations.graphql"
    lock = tmp_path / "schema.lock"
    target.write_bytes(content)
    lock.write_text(
        'source_repo = "browserless/bap-ts"\n'
        'source_path = "src/mutations.graphql"\n'
        f'source_commit = "{"a" * 40}"\n'
        "line_count = 1\n"
        f'sha256 = "{sha256(content).hexdigest()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_schema, "TARGET", target)
    monkeypatch.setattr(sync_schema, "LOCK", lock)
    monkeypatch.setattr(
        sync_schema,
        "automatic_candidate",
        lambda: (_ for _ in ()).throw(AssertionError("siblings were inspected")),
    )

    assert sync_schema.main(["auto", "--check"]) == 0


def test_external_schema_lock_records_file_name_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "vendored" / "mutations.graphql"
    lock = tmp_path / "schema.lock"
    schema = tmp_path / "source" / "mutations.graphql"
    schema.parent.mkdir()
    schema.write_text("type Query { a: String }\n", encoding="utf-8")
    monkeypatch.setattr(sync_schema, "TARGET", target)
    monkeypatch.setattr(sync_schema, "LOCK", lock)

    assert sync_schema.main(["--schema", str(schema)]) == 0

    text = lock.read_text(encoding="utf-8")
    assert tomllib.loads(text)["source_path"] == "mutations.graphql"
    assert str(tmp_path) not in text
    assert "/" not in text
