import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_public_text.py"
SPEC = importlib.util.spec_from_file_location("bap_check_public_text", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
check_public_text: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_public_text
SPEC.loader.exec_module(check_public_text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fix: ABC-1303 rename", ["ABC-1303"]),
        ("docs(XYZ-539): align", ["XYZ-539"]),
        ("feat: add handoffs QA-410", ["QA-410"]),
        ("see https://linear.app/x/issue/1", ["linear.app"]),
        ("thread https://ampcode.com/threads/T-1", ["ampcode.com/threads"]),
        ("see https://AMPCODE.com/threads/T-2", ["AMPCODE.com/threads"]),
        ("Co-authored-by: Amp <amp@ampcode.com>", []),
        ("https://acme.SLACK.com/archives/C1", ["SLACK.com"]),
        ("session https://app.devin.ai/sessions/1", ["devin.ai"]),
        ("https://app.usepylon.com/issues?issueNumber=1", ["usepylon.com"]),
        ("fix: read UTF-8 text", []),
        ("chore: SHA-256 and ISO-8601 and RFC-6455 and TLS-1 and HTTP-2", []),
        ("deps: patch CVE-2025-12345", []),
        ("fix: AES-256 and PEP-8 and ES-2022", []),
        ("call nonlinear.apply()", []),
        ("build(deps): bump websockets from 14.0 to 15.0", []),
        ("Closes #12", []),
        ("fix: abc-1301 lowercase", []),
        ("A-1 single letter", []),
        ("", []),
    ],
)
def test_find_violations(text: str, expected: list[str]) -> None:
    assert check_public_text.find_violations(text) == expected


def test_clean_pull_request_passes(capsys: pytest.CaptureFixture[str]) -> None:
    result = check_public_text.main(
        {"PR_TITLE": "docs: fix typo", "PR_BODY": "Closes #12"}
    )

    assert result == 0
    assert capsys.readouterr().out == ""


def test_ticket_id_in_title_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_public_text.main({"PR_TITLE": "fix: ABC-12 typo"}) == 1
    assert (
        "::error::PR title contains internal references: ABC-12"
        in capsys.readouterr().out
    )


def test_internal_link_in_body_fails(capsys: pytest.CaptureFixture[str]) -> None:
    result = check_public_text.main(
        {"PR_TITLE": "docs: fix typo", "PR_BODY": "see https://x.slack.com/a"}
    )

    assert result == 1
    assert "PR body contains internal references: slack.com" in (
        capsys.readouterr().out
    )


def test_review_bot_badge_in_body_passes(capsys: pytest.CaptureFixture[str]) -> None:
    badge = (
        '<a href="https://app.devin.ai/review/browserless/bap-py/pull/3" '
        'target="_blank"><picture><source media="(prefers-color-scheme: dark)" '
        'srcset="https://static.devin.ai/assets/gh-devin-review-dark.svg?v=4">'
        '<img src="https://static.devin.ai/assets/gh-devin-review-light.svg?v=4" '
        'alt="Devin Review"></picture></a>'
    )
    result = check_public_text.main({"PR_TITLE": "docs: fix typo", "PR_BODY": badge})

    assert result == 0
    assert capsys.readouterr().out == ""


def test_other_review_bot_links_still_fail(capsys: pytest.CaptureFixture[str]) -> None:
    result = check_public_text.main(
        {
            "PR_TITLE": "docs: fix typo",
            "PR_BODY": "see https://app.devin.ai/sessions/abc",
        }
    )

    assert result == 1
    assert "PR body contains internal references: devin.ai" in (capsys.readouterr().out)


def test_dependabot_body_is_not_checked(capsys: pytest.CaptureFixture[str]) -> None:
    result = check_public_text.main(
        {
            "PR_TITLE": "build(deps): bump websockets",
            "PR_BODY": "upstream ABC-1234 and https://x.slack.com/a",
            "PR_AUTHOR": "dependabot[bot]",
        }
    )

    assert result == 0
    assert capsys.readouterr().out == ""


def test_dependabot_title_is_checked() -> None:
    result = check_public_text.main(
        {"PR_TITLE": "build(deps): bump X ABC-1", "PR_AUTHOR": "dependabot[bot]"}
    )

    assert result == 1


def test_only_matches_are_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_public_text.main({"PR_TITLE": "$(touch pwned) ABC-1"}) == 1
    assert "$(touch pwned)" not in capsys.readouterr().out


def test_commit_messages_are_checked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        check_public_text,
        "commit_messages",
        lambda base, head: [
            "feat: ok\n\nCo-authored-by: Amp <amp@ampcode.com>",
            "fix: XYZ-9 bad",
        ],
    )

    result = check_public_text.main(
        {"PR_TITLE": "feat: ok", "BASE_SHA": "a", "HEAD_SHA": "b"}
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "PR commit 2 contains internal references: XYZ-9" in output
    assert "PR commit 1" not in output


def test_commit_messages_reads_git_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        result = subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("init", "--quiet")
    git("commit", "--quiet", "--allow-empty", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("commit", "--quiet", "--allow-empty", "-m", "feat: one")
    git("commit", "--quiet", "--allow-empty", "-m", "fix: two")

    assert check_public_text.commit_messages(base, "HEAD") == [
        "fix: two",
        "feat: one",
    ]
