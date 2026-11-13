# AGENTS.md

Guidance for coding agents working in this repository. Humans should start
with [CONTRIBUTING.md](./CONTRIBUTING.md); SDK users should read
[README.md](./README.md) and [llms.txt](./llms.txt).

## What this is

`browserless-bap` is the Python SDK for Browserless's Browser Automation Protocol. It
is a GraphQL-over-WebSocket client, not a CDP client. It offers equivalent
async and sync APIs with Playwright-style Python names.

## Source of truth

The vendored schema is `src/browserless_bap/mutations.graphql`. Generated modules and the
README/llms method lists come from `scripts/codegen.py` and are committed.
Never hand-edit generated output or content inside AUTOGEN markers.

To change generated output:

1. Update the schema with `scripts/sync_schema.py` or change generator inputs.
2. Run `python scripts/codegen.py`.
3. Run the drift check and commit the inputs and outputs together.

`src/browserless_bap/_version.py` is the single version source. Hatch reads the package
version from that file so installed wheels never need `pyproject.toml`. release-please
bumps it (with `.release-please-manifest.json` and `CHANGELOG.md`) in its release pull
request; never edit the version or the changelog by hand.

## Runtime constraints

- Python 3.11 or newer.
- `websockets` is the only runtime dependency.
- Keep GraphQL wire dictionaries zero-conversion; generated input/response
  dictionaries retain GraphQL field names.
- Transport clients must use `max_size=None`, `ping_interval=20`,
  `ping_timeout=None`, `open_timeout=None`, and `close_timeout=5`.
- Bound the whole WebSocket dial in `Transport._connect` with `asyncio.timeout`;
  keep `open_timeout=None`. Use `connect_timeout` (defaulting to `timeout`) in
  milliseconds; values at or below zero disable the deadline. Translate expiry
  to the SDK `TimeoutError` with `operation == "connect"`.
- Apply the single 5000 ms client headroom for server-timeout mutations in
  `Page._execute_operation`, not in individual methods. A connect deadline
  expiring is terminal for that page's connection; retries require a new page.
- Never block the asyncio loop with file I/O.
- Keep strong references to background tasks until completion.
- Sync callbacks run on their page's callback dispatcher, never the bridge loop.

## Commands

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy
pytest -m "not e2e"
python scripts/codegen.py
python scripts/sync_schema.py --check
```

Live tests are selected with `pytest -m e2e`, need `BROWSERLESS_TOKEN`, and use
`BROWSERLESS_URL` (default `wss://production-sfo.browserless.io/chromium/bql`).
Do not put tokens in source, tests, logs, screenshots, or recorded evidence.

## Before opening a PR

The offline suite, lint, strict typing, codegen drift check, and wheel smoke
must pass. Follow the pull request and public repository rules in
CONTRIBUTING.md. Publishing and deploying are human-owned; never create a
release, tag, or PyPI upload unless explicitly authorized.

## Public repository rules

Never write internal ticket IDs, internal tool links (issue tracker, chat,
coding-agent threads, support desk), private repository names or customer
details into PR titles, PR descriptions, commit messages, code comments, test
names, docs or review replies. CI enforces the title, description and commit
part. Link from the internal tracker to the PR, never the reverse.
