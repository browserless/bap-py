from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docs_cli_emits_deterministic_docusaurus_reference(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "scripts/docs.py",
        "--output",
        str(tmp_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    before = {
        path.relative_to(tmp_path): path.read_text(encoding="utf-8")
        for path in sorted(tmp_path.iterdir())
    }
    subprocess.run(command, cwd=ROOT, check=True)
    after = {
        path.relative_to(tmp_path): path.read_text(encoding="utf-8")
        for path in sorted(tmp_path.iterdir())
    }

    assert before == after
    assert "Type: `None`" not in "\n".join(before.values())
    assert set(before) == {
        Path("async-browser.mdx"),
        Path("async-browserless.mdx"),
        Path("async-element-handle.mdx"),
        Path("async-page.mdx"),
        Path("enums.mdx"),
        Path("errors.mdx"),
        Path("events.mdx"),
        Path("index.mdx"),
        Path("inputs.mdx"),
        Path("options.mdx"),
        Path("responses.mdx"),
        Path("sidebar.cjs"),
        Path("sync-browser.mdx"),
        Path("sync-browserless.mdx"),
        Path("sync-element-handle.mdx"),
        Path("sync-page.mdx"),
    }
    assert 'id: "sdk/bap-python/reference/async-page"' in before[Path("sidebar.cjs")]
    assert 'id: "sdk/bap-python/reference/index"' not in before[Path("sidebar.cjs")]
    assert "sdk/bql-python" not in before[Path("sidebar.cjs")]
    assert "id: index" in before[Path("index.mdx")]
    assert "](/sdk/bap-python/reference/async-browserless)" in before[Path("index.mdx")]
    assert "/sdk/bql-python" not in before[Path("index.mdx")]
    assert "## `goto`" in before[Path("async-page.mdx")]
    assert "## `click`" in before[Path("async-page.mdx")]
    assert "## `goto`" in before[Path("sync-page.mdx")]
    assert "## `closed`" in before[Path("async-page.mdx")]
    assert "Type: `bool`" in before[Path("async-page.mdx")]
    assert "## `closed`" in before[Path("sync-page.mdx")]
    assert "## `inner_html`" in before[Path("async-element-handle.mdx")]
    assert "## `selector`" in before[Path("sync-element-handle.mdx")]
    assert "listener_count(event: str) -> int" in before[Path("sync-page.mdx")]
    assert "Wait for the next event payload" in before[Path("async-page.mdx")]
    assert "Start tracking" in before[Path("sync-page.mdx")]
    assert "later `wait_for_event`" in before[Path("sync-page.mdx")]
    assert "waits indefinitely" not in before[Path("sync-page.mdx")]
    assert "page() -> AsyncContextManager[Page]" in before[Path("async-browser.mdx")]
    assert "async with browser.page() as page:" in before[Path("async-browser.mdx")]
    assert "page() -> ContextManager[Page]" in before[Path("sync-browser.mdx")]
    assert "with browser.page() as page:" in before[Path("sync-browser.mdx")]
    assert 'label: "Async API"' in before[Path("sidebar.cjs")]
    assert 'label: "Sync API"' in before[Path("sidebar.cjs")]
    assert 'label: "Types"' in before[Path("sidebar.cjs")]
    assert "## `GotoOptions`" in before[Path("options.mdx")]
    assert "Type: `Literal['screen', 'print']`" in before[Path("enums.mdx")]
    assert (
        "| `wait_until` | `NotRequired[WaitUntilGoto]` |" in before[Path("options.mdx")]
    )
    assert "## `HTTPResponse`" in before[Path("responses.mdx")]
    assert (
        "| `class` | `NotRequired[list[str] \\| None]` |"
        in before[Path("responses.mdx")]
    )
    assert "| `time` | `NotRequired[float \\| None]` |" in before[Path("responses.mdx")]
    assert "## `PageEventMap`" in before[Path("events.mdx")]


def test_codegen_cli_reports_external_docs_output(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "scripts/codegen.py",
        "--docs-output",
        str(tmp_path),
    ]

    first = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"wrote {tmp_path}/async-page.mdx" in first.stdout
    assert second.stdout.strip() == "generated output is current"
