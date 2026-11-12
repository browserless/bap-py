#!/usr/bin/env python3
"""Sync the vendored BrowserQL schema and record its provenance."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from graphql import parse

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "browserless_bap" / "mutations.graphql"
LOCK = ROOT / "schema.lock"
BAP_TS_SCHEMA = ROOT.parent / "bap-ts" / "src" / "mutations.graphql"


@dataclass(frozen=True)
class Candidate:
    source_repo: str
    source_path: str
    source_commit: str
    path: Path
    content: bytes

    @property
    def line_count(self) -> int:
        return len(self.content.splitlines())

    @property
    def digest(self) -> str:
        return sha256(self.content).hexdigest()


def git_commit(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_candidate(
    path: Path,
    *,
    source_repo: str,
    source_path: str,
    repository: Path | None,
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
        source_commit=git_commit(repository) if repository is not None else "external",
        path=path,
        content=content,
    )


def bap_ts_candidate() -> Candidate:
    return parse_candidate(
        BAP_TS_SCHEMA,
        source_repo="browserless/bap-ts",
        source_path="src/mutations.graphql",
        repository=BAP_TS_SCHEMA.parents[1],
    )


def external_candidate(path: Path) -> Candidate:
    resolved = path.resolve()
    return parse_candidate(
        resolved,
        source_repo="external",
        source_path=resolved.name,
        repository=None,
    )


def automatic_candidate() -> Candidate:
    try:
        return bap_ts_candidate()
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as error:
        raise FileNotFoundError(
            "No valid bap-ts schema found at ../bap-ts/src/mutations.graphql; "
            "pass --schema PATH"
        ) from error


def render_lock(candidate: Candidate) -> str:
    return (
        f'source_repo = "{candidate.source_repo}"\n'
        f'source_path = "{candidate.source_path}"\n'
        f'source_commit = "{candidate.source_commit}"\n'
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
        f"{lock['source_repo']}@{lock['source_commit']}:{lock['source_path']}"
    )
    return True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "mode",
        nargs="?",
        choices=["auto"],
        default="auto",
        help="sync from the sibling bap-ts checkout (default)",
    )
    source = result.add_mutually_exclusive_group()
    source.add_argument(
        "--from-bap-ts",
        action="store_true",
        help="read from ../bap-ts/src/mutations.graphql",
    )
    source.add_argument(
        "--schema",
        type=Path,
        help="read from an explicit schema path",
    )
    result.add_argument(
        "--check",
        action="store_true",
        help="validate the vendored schema against schema.lock",
    )
    return result


def selected_candidate(args: argparse.Namespace) -> Candidate:
    if args.from_bap_ts:
        return bap_ts_candidate()
    if args.schema is not None:
        return external_candidate(args.schema)
    return automatic_candidate()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.check:
        return 0 if check_lock() else 1

    try:
        candidate = selected_candidate(args)
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(candidate.content)
    LOCK.write_text(render_lock(candidate), encoding="utf-8", newline="\n")
    print(
        f"wrote {TARGET} and {LOCK} from {candidate.source_repo}:"
        f"{candidate.source_path} ({candidate.line_count} lines, {candidate.digest})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
