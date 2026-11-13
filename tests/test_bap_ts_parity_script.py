from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bap_ts_parity.py"


@pytest.fixture
def package(tmp_path: Path) -> Path:
    files = {
        "package.json": '{"name":"@browserless.io/bap-ts","version":"2.2.0"}',
        "src/mutations.graphql": "type Mutation { click: String }\n",
        "README.md": "<!-- AUTOGEN:method-table START -->\n"
        "| `click` | description |\n<!-- AUTOGEN:method-table END -->",
        "dist/graphql/mutations.js": "export const RESPONSE_FIELDS = {\n"
        "    ClickResponse: 'x y',\n};\n"
        "export const OPTIONAL_FIELDS = {\n"
        "    ClickResponse: {extra: 'z'},\n};\n"
        "export const ARG_TYPES = {\n"
        "    click: {timeout: 'Float', selector: 'String!'},\n};\n",
        "dist/page-generated.js": "this.execute(\n'click', {}, "
        "this.transportTimeout(timeout));\nthis.execute('plain', {});\n",
        "dist/page.js": "this.execute('click', {}, this.transportTimeout(timeout));\n",
    }
    for name, text in files.items():
        path = tmp_path / "package" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path / "package"


def run_script(
    package: Path, cwd: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    # Copy the script so its default output stays inside the temporary project.
    script = cwd / "scripts/bap_ts_parity.py"
    script.parent.mkdir(exist_ok=True)
    script.write_bytes(SCRIPT.read_bytes())
    return subprocess.run(
        [sys.executable, str(script), "--package", str(package), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_extract_directory_tarball_and_check(package: Path, tmp_path: Path) -> None:
    result = run_script(package, tmp_path)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "tests/fixtures/bap_ts_parity.json"
    original = output.read_text()
    snapshot = json.loads(original)
    assert snapshot == {
        "package": "@browserless.io/bap-ts",
        "version": "2.2.0",
        "schema_sha256": sha256(
            (package / "src/mutations.graphql").read_bytes()
        ).hexdigest(),
        "methods": ["click"],
        "response_fields": {"ClickResponse": "x y"},
        "optional_fields": {"ClickResponse": {"extra": "z"}},
        "arg_types": {"click": {"selector": "String!", "timeout": "Float"}},
        "cushioned_mutations": ["click"],
    }
    assert original == json.dumps(snapshot, sort_keys=True, indent=2) + "\n"
    archive = tmp_path / "package.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(package, arcname="package")
        # An unrelated archive member must never be extracted.
        member = tarfile.TarInfo("../escape")
        member.size = 1
        tar.addfile(member, io.BytesIO(b"x"))
    assert run_script(archive, tmp_path, "--check").returncode == 0
    assert not (tmp_path.parent / "escape").exists()
    snapshot["version"] = "changed"
    output.write_text(json.dumps(snapshot))
    result = run_script(archive, tmp_path, "--check")
    assert result.returncode == 1
    assert "version" in result.stdout
    assert json.loads(output.read_text())["version"] == "changed"


@pytest.mark.parametrize(
    "table",
    [
        "methods",
        "response_fields",
        "optional_fields",
        "arg_types",
        "cushioned_mutations",
    ],
)
def test_empty_collection_fails_loudly(
    package: Path, tmp_path: Path, table: str
) -> None:
    if table == "methods":
        (package / "README.md").write_text("")
    elif table == "cushioned_mutations":
        for name in ("page.js", "page-generated.js"):
            (package / "dist" / name).write_text("")
    else:
        path = package / "dist/graphql/mutations.js"
        path.write_text(path.read_text().replace(table.upper(), "REMOVED"))
    result = run_script(package, tmp_path)
    assert result.returncode != 0
    assert table in result.stderr


def test_rejects_wrong_package(package: Path, tmp_path: Path) -> None:
    (package / "package.json").write_text('{"name":"other","version":"2.2.0"}')
    result = run_script(package, tmp_path)
    assert result.returncode != 0
    assert "@browserless.io/bap-ts" in result.stderr
