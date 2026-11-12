#!/usr/bin/env python3
"""Generate Docusaurus reference files directly, without an MkDocs build."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.codegen.generate import generate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    generate(ROOT, docs_output=args.output)


if __name__ == "__main__":
    main()
