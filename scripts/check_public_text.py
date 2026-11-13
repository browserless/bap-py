#!/usr/bin/env python3
"""Reject pull request text that carries internal ticket IDs or internal links."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping

ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {"UTF", "SHA", "ISO", "CVE", "RFC", "TLS", "HTTP", "AES", "PEP", "ES"}
)
TICKET_ID = re.compile(r"\b([A-Z]{2,})-\d+")
# Only coding-agent thread links are blocked; its co-author trailer is allowed.
INTERNAL_HOST = re.compile(
    r"linear\.app\b|ampcode\.com/threads|slack\.com|devin\.ai|usepylon\.com",
    re.IGNORECASE,
)
# The code review bot adds a badge to every PR description. Only the badge's exact
# review link and image URLs are exempt; anything else on that host still fails,
# and nothing may follow them (no query strings or extra path segments).
PUBLIC_BOT_LINK = re.compile(
    r"https://app\.devin\.ai/review/browserless/bap-py/pull/\d+(?![\w/.?#&=%-])"
    r"|https://static\.devin\.ai/assets/gh-devin-review-(?:dark|light)\.svg"
    r"(?:\?v=\d+)?(?![\w/.?#&=%-])"
)
TITLE_ONLY_AUTHORS: frozenset[str] = frozenset({"dependabot[bot]"})


def find_violations(text: str) -> list[str]:
    text = PUBLIC_BOT_LINK.sub("", text)
    tickets = [
        match.group(0)
        for match in TICKET_ID.finditer(text)
        if match.group(1) not in ALLOWED_PREFIXES
    ]
    hosts = [match.group(0) for match in INTERNAL_HOST.finditer(text)]
    return tickets + hosts


def commit_messages(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%B%x00", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [message.strip() for message in result.stdout.split("\0") if message.strip()]


def main(environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    fields = [("title", env.get("PR_TITLE", ""))]
    if env.get("PR_AUTHOR", "") not in TITLE_ONLY_AUTHORS:
        fields.append(("body", env.get("PR_BODY", "")))
        base, head = env.get("BASE_SHA", ""), env.get("HEAD_SHA", "")
        if base and head:
            fields.extend(
                (f"commit {number}", message)
                for number, message in enumerate(commit_messages(base, head), 1)
            )

    failed = False
    for name, text in fields:
        violations = find_violations(text)
        if violations:
            failed = True
            # Print only the matches: the raw text is untrusted and could inject
            # workflow commands.
            matches = ", ".join(sorted(set(violations)))
            print(f"::error::PR {name} contains internal references: {matches}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
