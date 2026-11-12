# Contributing to browserless-bap

## Setup

Create a Python 3.11-or-newer virtual environment and install the editable
development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Development checks

Run these before opening a pull request:

```bash
ruff format --check .
ruff check .
mypy
pytest -m "not e2e"
python scripts/codegen.py
git diff --exit-code -- README.md llms.txt src/browserless_bap
python -m build
python -m venv /tmp/bap-wheel-smoke
/tmp/bap-wheel-smoke/bin/python -m pip install dist/*.whl
/tmp/bap-wheel-smoke/bin/python -c \
  "import browserless_bap, browserless_bap.sync_api; assert not hasattr(browserless_bap, 'schema_source')"
! python -m zipfile -l dist/*.whl | grep -q 'mutations.graphql'
```

### Live tests

The live suite (`pytest -m e2e`) connects to a real Browserless BrowserQL
endpoint and uses your account. It runs only when selected with `-m e2e` and is
skipped when `BROWSERLESS_TOKEN` is unset.
`BROWSERLESS_URL` defaults to `wss://production-sfo.browserless.io/chromium/bql`
and may be any `ws://` or `wss://` BrowserQL endpoint, for example another
region or a self-hosted server:

```bash
BROWSERLESS_TOKEN=your-api-token pytest -m e2e
BROWSERLESS_URL=wss://production-lon.browserless.io/chromium/bql BROWSERLESS_TOKEN=your-api-token pytest -m e2e
```

Never commit tokens or paste them into issues, pull requests, logs or
screenshots.

## Updating the BrowserQL schema

The integrity check is self-contained and needs no sibling repository:

```bash
python scripts/sync_schema.py --check
```

By default, syncing reads `../bap-ts/src/mutations.graphql` from a sibling
checkout of the TypeScript SDK:

```bash
python scripts/sync_schema.py
```

Contributors without that checkout can pass any schema file with `--schema`,
for example `src/mutations.graphql` from the published `@browserless.io/bap-ts`
npm package (version 2.2.0 or later):

```bash
python scripts/sync_schema.py --from-bap-ts
python scripts/sync_schema.py --schema /path/to/mutations.graphql
```

Schema and codegen changes must include `schema.lock` and all regenerated
files. Generated files and AUTOGEN regions must not be edited manually.

## API reference

The generated Python API reference is published at
<https://docs.browserless.io/bap/python/reference>. Maintainers regenerate it
with `python scripts/docs.py --output <directory>`, which writes Docusaurus
`.mdx` files, and publish the output to the documentation site.

## Pull requests

- Branch from `main` and keep changes focused.
- Use Conventional Commits-compatible titles and reference related GitHub
  issues (for example `Closes #123`).
- Include tests for behavior changes.
- Do not publish packages or create release tags from a pull request branch.

## Public repository rules

PR titles, descriptions, commit messages and review comments must not contain
internal ticket IDs (text like `ABC-123`), links to internal tools (issue
tracker, chat, coding-agent or support-desk links), private repository names,
or customer details. PR titles matter most: they become squash-commit subjects
and changelog entries.

CI (`Public PR rules`) rejects titles, descriptions and commit messages that
match these patterns; harmless technical identifiers such as `UTF-8`,
`SHA-256` and `CVE-2025-1234` are allowed. Maintainers link from the internal
tracker to the public PR, never the reverse.

PR titles also follow [Conventional Commits](https://www.conventionalcommits.org/):
`type: summary` or `type(scope): summary`, with type one of `feat`, `fix`,
`perf`, `revert`, `build`, `chore`, `ci`, `docs`, `style`, `refactor` or
`test`. The `PR title` check enforces this.

## Reporting security issues

Please report vulnerabilities privately as described in
[SECURITY.md](./SECURITY.md).

## Code of conduct

Everyone taking part in this project is expected to follow the
[Code of Conduct](./CODE_OF_CONDUCT.md).
