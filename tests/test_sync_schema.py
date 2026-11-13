import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import textwrap
import tomllib
import urllib.request
import urllib.response
from email.message import Message
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_schema.py"
SPEC = importlib.util.spec_from_file_location("bap_sync_schema", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync_schema: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_schema
SPEC.loader.exec_module(sync_schema)


def test_check_is_offline(
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
        "http_get",
        lambda *_: (_ for _ in ()).throw(AssertionError("network was used")),
    )

    assert sync_schema.main(["--check"]) == 0


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


SCHEMA = b"type Query { hello: String }\n"
MEMBER = "package/src/mutations.graphql"
REGISTRY = "https://registry.npmjs.org/"


def tarball(members: list[tuple[str, bytes, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(content)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "elsewhere"
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    data = tarball([(MEMBER, SCHEMA, tarfile.REGTYPE)])
    metadata: dict[str, Any] = {
        "version": "2.2.0",
        "gitHead": "a" * 40,
        "dist": {
            "tarball": REGISTRY + "@browserless.io/bap-ts/-/bap-ts-2.2.0.tgz",
            "integrity": "sha512-"
            + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        },
    }
    state: dict[str, Any] = {"metadata": metadata, "data": data, "requests": []}

    def get(url: str, limit: int) -> bytes:
        state["requests"].append(url)
        if url.startswith(REGISTRY + "@browserless.io%2fbap-ts/"):
            return json.dumps(metadata).encode()
        assert url == metadata["dist"]["tarball"]
        return bytes(state["data"])

    monkeypatch.setattr(sync_schema, "http_get", get, raising=False)
    monkeypatch.setattr(sync_schema, "TARGET", tmp_path / "mutations.graphql")
    monkeypatch.setattr(sync_schema, "LOCK", tmp_path / "schema.lock")
    return state


def test_from_npm_records_verified_provenance(registry: Any) -> None:
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0
    assert sync_schema.TARGET.read_bytes() == SCHEMA
    lock = tomllib.loads(sync_schema.LOCK.read_text())
    assert lock == {
        "source_repo": "browserless/bap-ts",
        "source_path": "src/mutations.graphql",
        "source_commit": "a" * 40,
        "npm_package": "@browserless.io/bap-ts",
        "npm_version": "2.2.0",
        "npm_integrity": registry["metadata"]["dist"]["integrity"],
        "line_count": 1,
        "sha256": sha256(SCHEMA).hexdigest(),
    }
    assert sync_schema.main(["--check"]) == 0


def test_latest_records_resolved_version(registry: Any) -> None:
    registry["metadata"]["version"] = "9.9.9"
    registry["metadata"]["dist"]["tarball"] = (
        REGISTRY + "@browserless.io/bap-ts/-/bap-ts-9.9.9.tgz"
    )
    assert sync_schema.main(["--from-npm", "latest"]) == 0
    assert registry["requests"][0].endswith("/latest")
    assert tomllib.loads(sync_schema.LOCK.read_text())["npm_version"] == "9.9.9"


@pytest.mark.parametrize("problem", ["mismatch", "algorithm", "url", "version"])
def test_invalid_registry_metadata_writes_nothing(registry: Any, problem: str) -> None:
    if problem == "mismatch":
        registry["data"] += b"tampered"
    elif problem == "algorithm":
        registry["metadata"]["dist"]["integrity"] = "sha1-abc"
    elif problem == "url":
        registry["metadata"]["dist"]["tarball"] = "https://example.com/evil.tgz"
    else:
        registry["metadata"]["version"] = "2.3.0"
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 1
    assert not sync_schema.TARGET.exists()
    assert not sync_schema.LOCK.exists()
    assert "https://example.com/evil.tgz" not in registry["requests"]


@pytest.mark.parametrize(
    "members",
    [
        [],
        [(MEMBER, b"", tarfile.SYMTYPE)],
        [(MEMBER, b"", tarfile.LNKTYPE)],
        [(MEMBER, SCHEMA, tarfile.REGTYPE)] * 2,
        [(MEMBER, b"not graphql", tarfile.REGTYPE)],
    ],
    ids=["missing", "symlink", "hardlink", "duplicate", "invalid-graphql"],
)
def test_invalid_archive_preserves_outputs(
    registry: Any,
    members: list[tuple[str, bytes, bytes]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry["data"] = tarball(members)
    registry["metadata"]["dist"]["integrity"] = (
        "sha512-" + base64.b64encode(hashlib.sha512(registry["data"]).digest()).decode()
    )
    sync_schema.TARGET.write_bytes(b"original schema")
    original_lock = 'source_repo = "external"\n'
    sync_schema.LOCK.write_text(original_lock)
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 1
    assert sync_schema.TARGET.read_bytes() == b"original schema"
    assert sync_schema.LOCK.read_text() == original_lock
    message = capsys.readouterr().err
    assert MEMBER in message
    if members and members[0][1] == b"not graphql":
        assert "Invalid GraphQL schema" in message
    elif len(members) != 1:
        assert "expected exactly one" in message
    else:
        assert "must be a regular file" in message


def test_unrelated_archive_paths_are_never_extracted(
    registry: Any, tmp_path: Path
) -> None:
    registry["data"] = tarball(
        [
            (MEMBER, SCHEMA, tarfile.REGTYPE),
            ("package/../evil", b"bad", tarfile.REGTYPE),
            ("/abs", b"bad", tarfile.REGTYPE),
        ]
    )
    registry["metadata"]["dist"]["integrity"] = (
        "sha512-" + base64.b64encode(hashlib.sha512(registry["data"]).digest()).decode()
    )
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0
    assert set(tmp_path.iterdir()) == {sync_schema.TARGET, sync_schema.LOCK}


@pytest.mark.parametrize("limit", ["MAX_UNPACKED_BYTES", "MAX_SCHEMA_BYTES"])
def test_archive_size_limits_write_nothing(
    registry: Any, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    monkeypatch.setattr(sync_schema, limit, 10, raising=False)
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 1
    assert not sync_schema.TARGET.exists()
    assert not sync_schema.LOCK.exists()


def test_missing_git_head_records_unknown(registry: Any) -> None:
    del registry["metadata"]["gitHead"]
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0
    assert tomllib.loads(sync_schema.LOCK.read_text())["source_commit"] == "unknown"


def test_same_version_integrity_cannot_change(
    registry: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0
    original = sync_schema.TARGET.read_bytes()
    text = sync_schema.LOCK.read_text().replace(
        registry["metadata"]["dist"]["integrity"], "sha512-" + "A" * 86 + "=="
    )
    sync_schema.LOCK.write_text(text)
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert sync_schema.TARGET.read_bytes() == original
    assert sync_schema.LOCK.read_text() == text
    sync_schema.LOCK.write_text(
        text.replace(
            "sha512-" + "A" * 86 + "==", registry["metadata"]["dist"]["integrity"]
        )
    )
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0


@pytest.mark.parametrize(
    "args", [[], ["--from-npm", "../2.2.0"], ["--from-npm", "2.2"]]
)
def test_invalid_cli_never_downloads(registry: Any, args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        sync_schema.main(args)
    assert error.value.code == 2
    assert registry["requests"] == []


@pytest.mark.parametrize("problem", ["partial", "integrity", "package"])
def test_check_rejects_invalid_npm_provenance(registry: Any, problem: str) -> None:
    assert sync_schema.main(["--from-npm", "2.2.0"]) == 0
    text = sync_schema.LOCK.read_text()
    if problem == "partial":
        text = text.replace('npm_version = "2.2.0"\n', "")
    elif problem == "integrity":
        text = text.replace(registry["metadata"]["dist"]["integrity"], "sha1-abc")
    else:
        text = text.replace(
            'npm_package = "@browserless.io/bap-ts"', 'npm_package = "other"'
        )
    sync_schema.LOCK.write_text(text)
    assert sync_schema.main(["--check"]) == 1


@pytest.mark.parametrize(
    ("url", "body", "valid"),
    [
        ("https://example.com/x", b"a", False),
        (REGISTRY, b"abcd", False),
        (REGISTRY, b"abc", True),
    ],
)
def test_http_response_host_and_size(
    monkeypatch: pytest.MonkeyPatch, url: str, body: bytes, valid: bool
) -> None:
    class Response(io.BytesIO):
        def geturl(self) -> str:
            return url

    monkeypatch.setattr(
        sync_schema.urllib.request,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda *_a, **_kw: Response(body)),
    )
    if valid:
        assert sync_schema.http_get(REGISTRY, 3) == body
    else:
        with pytest.raises(ValueError):
            sync_schema.http_get(REGISTRY, 3)


@pytest.mark.parametrize(
    "location", ["https://example.com/x", "http://registry.npmjs.org/x"]
)
def test_http_redirect_is_rejected_before_following_or_reading(
    monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    requests: list[str] = []

    class Body(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise AssertionError("redirect body must not be consumed")

    def response(_self: Any, request: urllib.request.Request) -> Any:
        requests.append(request.full_url)
        if len(requests) > 1:
            raise AssertionError("redirect target must not be requested")
        headers = Message()
        headers["Location"] = location
        result: Any = urllib.response.addinfourl(Body(), headers, request.full_url, 302)
        result.msg = "Found"
        return result

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", response)
    with pytest.raises(ValueError, match="redirect"):
        sync_schema.http_get(REGISTRY, 3)
    assert requests == [REGISTRY]


@pytest.mark.parametrize(
    ("branch_exists", "open_pr", "create", "push"),
    [
        (True, False, True, False),
        (False, False, True, True),
        (True, True, False, False),
    ],
)
def test_schema_workflow_recovers_branch_without_pr(
    branch_exists: bool,
    open_pr: bool,
    create: bool,
    push: bool,
) -> None:
    workflow = (SCRIPT.parents[1] / ".github/workflows/schema-sync.yml").read_text()
    script = textwrap.dedent(workflow.rsplit("run: |\n", 1)[1])
    fake_commands = """
    git() {
      if [ "$1" = ls-remote ]; then return "$BRANCH_MISSING"; fi
      echo "git $*"
    }
    gh() {
      if [ "$1 $2" = "pr list" ]; then
        if [ "$OPEN_PR" = 1 ]; then
          echo "https://github.com/browserless/bap-py/pull/123"
        fi
      else
        echo "created PR"
      fi
    }
    """
    result = subprocess.run(
        ["bash", "-e", "-c", fake_commands + script],
        env={
            **os.environ,
            "BRANCH_MISSING": "0" if branch_exists else "2",
            "OPEN_PR": "1" if open_pr else "0",
            "VERSION": "2.3.0",
            "GITHUB_REPOSITORY": "browserless/bap-py",
            "RUNNER_TEMP": "/unused",
            "GH_TOKEN": "test-token",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ("created PR" in result.stdout) is create
    assert ("git push" in result.stdout) is push
