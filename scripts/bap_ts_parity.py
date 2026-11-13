#!/usr/bin/env python3
"""Extract an offline parity snapshot from the published bap-ts npm package."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tarfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

TARGET = Path(__file__).resolve().parents[1] / "tests/fixtures/bap_ts_parity.json"
PACKAGE = "@browserless.io/bap-ts"


def extract(read: Callable[[str], bytes]) -> dict[str, Any]:
    metadata = json.loads(read("package.json"))
    if metadata.get("name") != PACKAGE:
        raise ValueError(f"Expected package {PACKAGE}")
    js = read("dist/graphql/mutations.js").decode("utf-8")

    def table(name: str, *, nested: bool = False) -> dict[str, Any]:
        block = re.search(rf"export const {name.upper()} = {{(.*?)\n}};", js, re.S)
        if not block:
            raise ValueError(f"Missing table: {name}")
        if nested:
            result = {
                key: dict(re.findall(r"(\w+): '([^']*)'", values))
                for key, values in re.findall(r"^\s+(\w+): \{(.*)\},?$", block[1], re.M)
            }
        else:
            result = dict(re.findall(r"^\s+(\w+): '([^']*)',", block[1], re.M))
        if not result:
            raise ValueError(f"Empty table: {name}")
        return result

    readme = read("README.md").decode("utf-8")
    block = re.search(
        r"<!-- AUTOGEN:method-table START -->(.*?)<!-- AUTOGEN:method-table END -->",
        readme,
        re.S,
    )
    methods = sorted(re.findall(r"^\| `([^`]+)` \|", block[1] if block else "", re.M))
    if not methods:
        raise ValueError("Empty table: methods")
    cushioned = sorted(
        {
            name
            for file in ("dist/page-generated.js", "dist/page.js")
            for name, remainder in re.findall(
                r"this\.execute\(\s*'(\w+)'(.*?)\);\n",
                read(file).decode("utf-8"),
                re.S,
            )
            if "this.transportTimeout(" in remainder
        }
    )
    if not cushioned:
        raise ValueError("Empty table: cushioned_mutations")
    return {
        "package": metadata["name"],
        "version": metadata["version"],
        "schema_sha256": sha256(read("src/mutations.graphql")).hexdigest(),
        "methods": methods,
        "response_fields": table("response_fields"),
        "optional_fields": table("optional_fields", nested=True),
        "arg_types": table("arg_types", nested=True),
        "cushioned_mutations": cushioned,
    }


def snapshot(package: Path) -> dict[str, Any]:
    if package.is_dir():
        return extract(lambda name: (package / name).read_bytes())
    with tarfile.open(package, "r:*") as archive:

        def read(name: str) -> bytes:
            member = archive.extractfile(f"package/{name}")
            if member is None:
                raise ValueError(f"Missing package file: {name}")
            with member:
                return member.read()

        return extract(read)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        rendered = json.dumps(snapshot(args.package), sort_keys=True, indent=2) + "\n"
        if args.check:
            current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
            if current != rendered:
                print(
                    "".join(
                        difflib.unified_diff(
                            current.splitlines(keepends=True),
                            rendered.splitlines(keepends=True),
                            fromfile="committed snapshot",
                            tofile="package snapshot",
                        )
                    ),
                    end="",
                )
                return 1
        else:
            TARGET.parent.mkdir(parents=True, exist_ok=True)
            TARGET.write_text(rendered, encoding="utf-8")
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f"Parity extraction failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
