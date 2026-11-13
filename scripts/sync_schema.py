#!/usr/bin/env python3
"""Sync the vendored BrowserQL schema and record its provenance."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import re
import sys
import tarfile
import tomllib
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from graphql import parse

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "browserless_bap" / "mutations.graphql"
LOCK = ROOT / "schema.lock"
NPM_PACKAGE = "@browserless.io/bap-ts"
NPM_REGISTRY_HOST = "registry.npmjs.org"
NPM_METADATA_URL = "https://registry.npmjs.org/@browserless.io%2fbap-ts/{version}"
NPM_TARBALL_URL = (
    "https://registry.npmjs.org/@browserless.io/bap-ts/-/bap-ts-{version}.tgz"
)
NPM_SCHEMA_MEMBER = "package/src/mutations.graphql"
NPM_SOURCE_PATH = "src/mutations.graphql"
MAX_METADATA_BYTES = 1 << 20
MAX_TARBALL_BYTES = 10 << 20
MAX_UNPACKED_BYTES = 64 << 20
MAX_SCHEMA_BYTES = 8 << 20
TIMEOUT_SECONDS = 30
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?")
INTEGRITY_PATTERN = re.compile(r"sha512-[A-Za-z0-9+/]{86}==")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Candidate:
    source_repo: str
    source_path: str
    source_commit: str
    path: Path
    content: bytes
    npm_package: str | None = None
    npm_version: str | None = None
    npm_integrity: str | None = None

    @property
    def line_count(self) -> int:
        return len(self.content.splitlines())

    @property
    def digest(self) -> str:
        return sha256(self.content).hexdigest()


def http_get(url: str, limit: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "browserless-bap-schema-sync"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        destination = urllib.parse.urlsplit(response.geturl())
        if destination.scheme != "https" or destination.hostname != NPM_REGISTRY_HOST:
            raise ValueError("response must come from the HTTPS npm registry")
        data: bytes = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"response from {url} exceeds {limit} bytes")
    return data


def npm_version_arg(value: str) -> str:
    if value == "latest" or VERSION_PATTERN.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError(
        "expected an exact version such as 2.2.0, or latest"
    )


def read_schema_member(tarball: bytes) -> bytes:
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    raw = decompressor.decompress(tarball, MAX_UNPACKED_BYTES)
    if decompressor.unconsumed_tail:
        raise ValueError(f"unpacked tarball exceeds {MAX_UNPACKED_BYTES} bytes")
    if not decompressor.eof:
        raise ValueError("truncated tarball")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = [m for m in archive.getmembers() if m.name == NPM_SCHEMA_MEMBER]
        if len(members) != 1:
            raise ValueError(f"expected exactly one {NPM_SCHEMA_MEMBER} member")
        member = members[0]
        if not member.isreg():
            raise ValueError(f"{NPM_SCHEMA_MEMBER} must be a regular file")
        if member.size > MAX_SCHEMA_BYTES:
            raise ValueError(f"{NPM_SCHEMA_MEMBER} exceeds {MAX_SCHEMA_BYTES} bytes")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError(f"cannot read {NPM_SCHEMA_MEMBER}")
        with stream:
            return stream.read()


def npm_candidate(spec: str) -> Candidate:
    meta = json.loads(
        http_get(NPM_METADATA_URL.format(version=spec), MAX_METADATA_BYTES)
    )
    version = meta["version"]
    if not VERSION_PATTERN.fullmatch(version) or (spec != "latest" and version != spec):
        raise ValueError("npm metadata version does not match the requested version")
    integrity = meta["dist"]["integrity"]
    if not INTEGRITY_PATTERN.fullmatch(integrity):
        raise ValueError("npm integrity must be a sha512 hash")
    url = NPM_TARBALL_URL.format(version=version)
    if meta["dist"]["tarball"] != url:
        raise ValueError("npm tarball URL does not match the expected registry URL")
    data = http_get(url, MAX_TARBALL_BYTES)
    if not hmac.compare_digest(
        base64.b64decode(integrity.removeprefix("sha512-")),
        hashlib.sha512(data).digest(),
    ):
        raise ValueError(f"integrity mismatch for {NPM_PACKAGE}@{version}")
    content = read_schema_member(data)
    try:
        parse(content.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid GraphQL schema: {NPM_SCHEMA_MEMBER}") from error
    commit = meta.get("gitHead")
    return Candidate(
        source_repo="browserless/bap-ts",
        source_path=NPM_SOURCE_PATH,
        source_commit=(
            commit
            if isinstance(commit, str) and COMMIT_PATTERN.fullmatch(commit)
            else "unknown"
        ),
        path=Path(NPM_SCHEMA_MEMBER),
        content=content,
        npm_package=NPM_PACKAGE,
        npm_version=version,
        npm_integrity=integrity,
    )


def parse_candidate(
    path: Path,
    *,
    source_repo: str,
    source_path: str,
    source_commit: str,
) -> Candidate:
    if not path.is_file():
        raise FileNotFoundError(f"Schema source not found: {path}")

    content = path.read_bytes()
    try:
        parse(content.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid GraphQL schema: {path}") from error

    return Candidate(
        source_repo=source_repo,
        source_path=source_path,
        source_commit=source_commit,
        path=path,
        content=content,
    )


def external_candidate(path: Path) -> Candidate:
    resolved = path.resolve()
    return parse_candidate(
        resolved,
        source_repo="external",
        source_path=resolved.name,
        source_commit="external",
    )


def render_lock(candidate: Candidate) -> str:
    npm = (
        f'npm_package = "{candidate.npm_package}"\n'
        f'npm_version = "{candidate.npm_version}"\n'
        f'npm_integrity = "{candidate.npm_integrity}"\n'
        if candidate.npm_version is not None
        else ""
    )
    return (
        f'source_repo = "{candidate.source_repo}"\n'
        f'source_path = "{candidate.source_path}"\n'
        f'source_commit = "{candidate.source_commit}"\n'
        f"{npm}"
        f"line_count = {candidate.line_count}\n"
        f'sha256 = "{candidate.digest}"\n'
    )


def check_lock() -> bool:
    if not TARGET.is_file():
        print(f"Vendored schema not found: {TARGET}", file=sys.stderr)
        return False
    if not LOCK.is_file():
        print(f"Schema lock not found: {LOCK}", file=sys.stderr)
        return False

    content = TARGET.read_bytes()
    try:
        parse(content.decode("utf-8"))
    except Exception as error:
        print(f"Invalid vendored GraphQL schema: {error}", file=sys.stderr)
        return False

    try:
        lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"Invalid schema lock: {error}", file=sys.stderr)
        return False

    required = {
        "source_repo",
        "source_path",
        "source_commit",
        "line_count",
        "sha256",
    }
    missing = sorted(required.difference(lock))
    if missing:
        print(f"schema.lock is missing: {', '.join(missing)}", file=sys.stderr)
        return False

    npm_fields = {"npm_package", "npm_version", "npm_integrity"}
    npm = ""
    if npm_fields.intersection(lock):
        if (
            not npm_fields.issubset(lock)
            or lock["npm_package"] != NPM_PACKAGE
            or not isinstance(lock["npm_version"], str)
            or not VERSION_PATTERN.fullmatch(lock["npm_version"])
            or not isinstance(lock["npm_integrity"], str)
            or not INTEGRITY_PATTERN.fullmatch(lock["npm_integrity"])
        ):
            print(
                "schema.lock has invalid npm provenance: expected package, exact "
                "version and sha512 integrity",
                file=sys.stderr,
            )
            return False
        npm = f" (npm {NPM_PACKAGE}@{lock['npm_version']})"

    actual_lines = len(content.splitlines())
    actual_digest = sha256(content).hexdigest()
    if lock["line_count"] != actual_lines or lock["sha256"] != actual_digest:
        print(
            "Vendored schema does not match schema.lock:\n"
            f"  line_count: lock={lock['line_count']} actual={actual_lines}\n"
            f"  sha256: lock={lock['sha256']} actual={actual_digest}",
            file=sys.stderr,
        )
        return False

    print(
        "browserless-bap schema lock is current "
        f"({actual_lines} lines, {actual_digest}) from "
        f"{lock['source_repo']}@{lock['source_commit']}:{lock['source_path']}{npm}"
    )
    return True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--from-npm",
        metavar="VERSION",
        type=npm_version_arg,
        help="download src/mutations.graphql from this @browserless.io/bap-ts "
        "npm release (exact version such as 2.2.0, or latest)",
    )
    source.add_argument(
        "--schema",
        type=Path,
        help="read from an explicit schema path",
    )
    source.add_argument(
        "--check",
        action="store_true",
        help="validate the vendored schema against schema.lock",
    )
    return result


def selected_candidate(args: argparse.Namespace) -> Candidate:
    if args.from_npm is not None:
        return npm_candidate(args.from_npm)
    return external_candidate(args.schema)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.check:
        return 0 if check_lock() else 1

    try:
        candidate = selected_candidate(args)
        if candidate.npm_version is not None and LOCK.exists():
            lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
            if (
                lock.get("npm_version") == candidate.npm_version
                and lock.get("npm_integrity") != candidate.npm_integrity
            ):
                raise ValueError(
                    f"npm integrity for {NPM_PACKAGE}@{candidate.npm_version} "
                    "differs from schema.lock; refusing to overwrite"
                )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        zlib.error,
    ) as error:
        print(error, file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(candidate.content)
    LOCK.write_text(render_lock(candidate), encoding="utf-8", newline="\n")
    source = (
        f"{NPM_PACKAGE}@{candidate.npm_version}"
        if candidate.npm_version
        else candidate.source_repo
    )
    print(
        f"wrote {TARGET} and {LOCK} from {source}:"
        f"{candidate.source_path} ({candidate.line_count} lines, {candidate.digest})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
