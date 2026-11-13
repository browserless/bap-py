from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config.docs import LLMS_END, LLMS_START, README_END, README_START
from .emit_docs import emit_reference, llms_method_list, readme_table
from .emit_enums import emit as emit_enums
from .emit_events import emit_subscriptions
from .emit_events import emit_types as emit_events
from .emit_inputs import emit as emit_inputs
from .emit_operations import emit as emit_operations
from .emit_options import emit as emit_options
from .emit_page import emit_async, emit_sync
from .emit_responses import emit as emit_responses
from .emit_types_init import emit as emit_types_init
from .model import build_models
from .schema import Schema
from .writer import splice_region, write_if_changed

GENERATED_OUTPUTS = (
    "src/browserless_bap/types/enums.py",
    "src/browserless_bap/types/inputs.py",
    "src/browserless_bap/types/responses.py",
    "src/browserless_bap/types/options.py",
    "src/browserless_bap/types/events.py",
    "src/browserless_bap/types/__init__.py",
    "src/browserless_bap/graphql/mutations.py",
    "src/browserless_bap/graphql/subscriptions.py",
    "src/browserless_bap/_page_generated.py",
    "src/browserless_bap/sync_api/_page_generated.py",
)


def generate(root: Path, *, docs_output: Path | None = None) -> list[Path]:
    schema = Schema.load(root / "src" / "browserless_bap" / "mutations.graphql")
    models = build_models(schema)
    rendered = (
        emit_enums(schema),
        emit_inputs(schema),
        emit_responses(schema),
        emit_options(schema),
        emit_events(schema),
        emit_types_init(schema),
        emit_operations(schema),
        emit_subscriptions(schema),
        emit_async(models),
        emit_sync(models),
    )
    outputs = {
        root / path: content
        for path, content in zip(GENERATED_OUTPUTS, rendered, strict=True)
    }
    for path in outputs:
        if path.name == "_page_generated.py":
            outputs[path] = subprocess.run(
                [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(path)],
                input=outputs[path],
                capture_output=True,
                text=True,
                check=True,
                cwd=root,
            ).stdout
    changed = [
        path for path, content in outputs.items() if write_if_changed(path, content)
    ]
    if splice_region(
        root / "README.md", README_START, README_END, readme_table(models)
    ):
        changed.append(root / "README.md")
    if splice_region(root / "llms.txt", LLMS_START, LLMS_END, llms_method_list(models)):
        changed.append(root / "llms.txt")
    if docs_output is not None:
        changed.extend(emit_reference(models, docs_output, root))
    return changed
