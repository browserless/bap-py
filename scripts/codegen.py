#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from codegen.generate import generate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate browserless-bap from BrowserQL SDL"
    )
    parser.add_argument(
        "--docs-output",
        type=Path,
        help="optional Docusaurus docs directory for generated reference MDX",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    changed = generate(root, docs_output=args.docs_output)
    for path in changed:
        display = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"wrote {display}")
    if not changed:
        print("generated output is current")


if __name__ == "__main__":
    main()
