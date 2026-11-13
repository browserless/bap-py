import re
from pathlib import Path

import pytest
from mypy import api

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("document", ["README.md", "llms.txt"])
def test_self_contained_examples_typecheck(document: str, tmp_path: Path) -> None:
    blocks = [
        block
        for block in re.findall(
            r"^```python\s*\n(.*?)^```", (ROOT / document).read_text(), re.M | re.S
        )
        if "import browserless_bap" in block
    ]
    if document == "README.md":
        assert len(blocks) >= 2
        assert any("import browserless_bap.sync_api" in block for block in blocks)
    for index, block in enumerate(blocks):
        example = tmp_path / f"example_{index}.py"
        example.write_text(block)
        stdout, stderr, status = api.run(
            [
                "--strict",
                "--no-incremental",
                "--cache-dir",
                str(tmp_path / ".mypy_cache"),
                str(example),
            ]
        )
        assert status == 0, f"{document} block {index}:\n{stdout}{stderr}"
