# browserless-bap

The Python client for Browserless's Browser Automation Protocol (BAP).
`browserless-bap` provides Playwright-style async and sync APIs over Browserless's
GraphQL-over-WebSocket transport.

## Requirements

- Python 3.11 or newer
- A Browserless API token for live use

## Install

```bash
pip install browserless-bap
```

## Quick start

```python
import asyncio

import browserless_bap as bap


async def run() -> None:
    async with bap.Browserless.connect(
        browser_ws_endpoint="wss://production-sfo.browserless.io/chromium/bql",
        token="your-api-token",
    ) as browser:
        async with browser.page() as page:
            await page.goto("https://example.com")
            print(await page.title())


asyncio.run(run())
```

The same script with the sync API, from `browserless_bap.sync_api`:

```python
import browserless_bap.sync_api as bap

with bap.Browserless.connect(
    browser_ws_endpoint="wss://production-sfo.browserless.io/chromium/bql",
    token="your-api-token",
) as browser:
    with browser.page() as page:
        page.goto("https://example.com")
        print(page.title())
```

> [!TIP]
> Jupyter notebooks already run an asyncio event loop, so use the async API
> there and replace `asyncio.run(run())` with `await run()`. The sync API
> raises `RuntimeError` inside a running event loop.

## Logging

The SDK uses Python's `logging` module with the `browserless_bap` logger.
WebSocket frame logs use its child logger, `browserless_bap.websockets`;
setting the parent to `DEBUG` enables both SDK diagnostics and frame logs.

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("browserless_bap").setLevel(logging.DEBUG)
```

The `browserless_bap.websockets` logger redacts tokens and `Authorization` header
values. Frame logs can still contain page content and other application data;
review them before sharing.

## Timeouts

Timeout values are in milliseconds. The default per-step `timeout` is `30000`.
For mutations with a server-side timeout, the client adds `5000` ms of headroom
once, allowing the server to return its timeout response before the client deadline.

`connect_timeout` defaults to `timeout` and bounds the entire WebSocket dial,
including connection setup and handshake. A value of `0` or less disables that
connection deadline. Connection timeouts raise the SDK's `browserless_bap.TimeoutError`
with `operation == "connect"`.

A connect deadline expiring is terminal for that page's connection. To retry,
create a new page rather than reusing the timed-out page. These rules apply to
both the async and sync APIs. Live URL completion waits have their own timeout
behavior, described below.

## API methods

This table is generated from the vendored GraphQL schema. Do not edit the
contents between the markers by hand.

<!-- AUTOGEN:method-table START -->

| Method | Source mutation | Returns | Playwright-named |
| ------ | --------------- | ------- | ---------------- |
| `add_cookies` | `cookies` | `CookieResponse` | ✅ |
| `add_script_tag` | `addScriptTag` | `AddScriptTagResponse` | ✅ |
| `add_style_tag` | `addStyleTag` | `AddStyleTagResponse` | ✅ |
| `authenticate` | `authenticate` | `HTTPResponse \| None` | — |
| `check` | `checkbox` | `ClickResponse` | — |
| `click` | `click` | `ClickResponse` | ✅ |
| `close` | `—` | `None` | ✅ |
| `close_live_url` | `closeLiveURL` | `CloseLiveURLResponse` | — |
| `content` | `html` | `str` | ✅ |
| `cookies` | `cookies` | `list[StandardCookie]` | ✅ |
| `emulate_media` | `emulateMediaType` | `EmulateMediaTypeResponse` | ✅ |
| `eval_on_selector` | `text` | `str` | — |
| `eval_on_selector_all` | `mapSelector` | `list[MapSelectorResponse]` | — |
| `evaluate` | `evaluate` | `str \| None` | ✅ |
| `fulfill` | `fulfill` | `FulfillResponse` | — |
| `go_back` | `back` | `HTTPResponse \| None` | ✅ |
| `go_forward` | `forward` | `HTTPResponse \| None` | ✅ |
| `goto` | `goto` | `HTTPResponse \| None` | ✅ |
| `hover` | `hover` | `HoverResponse` | ✅ |
| `html` | `html` | `HTMLResponse` | — |
| `live_url` | `liveURL` | `LiveURLResponse` | — |
| `load_secret` | `loadSecret` | `LoadSecretResponse` | — |
| `map_selector` | `mapSelector` | `list[MapSelectorResponse]` | — |
| `markdown` | `markdown` | `MarkdownResponse` | — |
| `pdf` | `pdf` | `bytes` | ✅ |
| `preferences` | `preferences` | `DefaultResponse` | — |
| `proxy` | `proxy` | `ProxyResponse` | — |
| `query_selector` | `querySelector` | `ElementHandle \| None` | ✅ |
| `query_selector_all` | `querySelectorAll` | `list[ElementHandle]` | ✅ |
| `reconnect` | `reconnect` | `ReconnectionResponse` | — |
| `reject` | `reject` | `RejectResponse` | — |
| `reload` | `reload` | `HTTPResponse \| None` | ✅ |
| `request` | `request` | `list[RequestResponse]` | — |
| `response` | `response` | `list[ResponseResponse]` | — |
| `screenshot` | `screenshot` | `bytes` | ✅ |
| `scroll` | `scroll` | `ScrollResponse` | — |
| `select_option` | `select` | `SelectResponse` | ✅ |
| `send` | `—` | `T` | — |
| `set_content` | `content` | `HTTPResponse \| None` | ✅ |
| `set_extra_http_headers` | `setExtraHTTPHeaders` | `HTTPHeadersResponse` | ✅ |
| `set_java_script_enabled` | `javaScriptEnabled` | `JavaScriptResponse` | — |
| `set_user_agent` | `userAgent` | `UserAgentResponse` | ✅ |
| `set_viewport_size` | `viewport` | `ViewportResponse` | ✅ |
| `solve` | `solve` | `CaptchaResponse` | — |
| `solve_image_captcha` | `solveImageCaptcha` | `CaptchaResponse` | — |
| `stop_session_recording` | `stopSessionRecording` | `StopSessionRecordingResponse` | — |
| `switch_to_window` | `switchToWindow` | `SwitchWindowResponse` | — |
| `text` | `text` | `TextResponse` | — |
| `title` | `title` | `str` | ✅ |
| `type` | `type` | `TypeResponse` | ✅ |
| `uncheck` | `checkbox` | `ClickResponse` | — |
| `url` | `url` | `str` | ✅ |
| `wait_for_event` | `waitForEvent` | `WaitForEvent` | — |
| `wait_for_function` | `waitForFunction` | `WaitForFunction` | ✅ |
| `wait_for_live_complete` | `liveComplete` | `LiveURLCompleteEvent` | — |
| `wait_for_navigation` | `waitForNavigation` | `HTTPResponse` | ✅ |
| `wait_for_network_idle` | `waitForNetworkIdle` | `WaitForTimeoutResponse` | — |
| `wait_for_request` | `waitForRequest` | `WaitForRequestResponse` | ✅ |
| `wait_for_response` | `waitForResponse` | `WaitForResponseResponse` | ✅ |
| `wait_for_selector` | `waitForSelector` | `WaitForSelectorResponse` | ✅ |
| `wait_for_timeout` | `waitForTimeout` | `None` | ✅ |
| `watch_event` | `watchEvent` | `WaitForEvent` | — |

<!-- AUTOGEN:method-table END -->

## Response keys and optional fields

Options and keyword arguments use `snake_case`; returned dictionaries keep the
server's field names (`liveURLId`, `httpOnly`, `childElementCount`), as Playwright
for Python does for cookies.

`query_selector()` and `query_selector_all()` fetch element HTML only with
`html=True`. Reading a handle's `inner_html` or `outer_html` without requesting it
raises `BAPValueError` with a hint. This also applies to element-scoped queries.
`response()` omits bodies by default; pass `body=True` to fetch them, or
`body_encoding=True` to fetch both the body and its `base64Encoded` flag.

`eval_on_selector()` returns the first matching element's text, and
`eval_on_selector_all()` returns element details. Unlike Playwright's methods,
neither accepts a page function.

SDK exceptions are `BAPTimeoutError`, `BAPConnectionError` and `BAPValueError`.
They still subclass Python's matching built-in exceptions; the builtin-named SDK
exports have been removed.

## Schema and generated code

`src/browserless_bap/mutations.graphql` is the vendored GraphQL schema. Its full digest,
line count, and source provenance are committed in `schema.lock`. Verify the
vendored schema without requiring any sibling checkout:

```bash
python scripts/sync_schema.py --check
```

Syncing downloads `src/mutations.graphql` from a named `@browserless.io/bap-ts`
npm release (version 2.2.0 or later), verifies npm's integrity hash, and records
the resolved version and integrity hash in `schema.lock`. No Node.js or private
checkout is required:

```bash
python scripts/sync_schema.py --from-npm 2.2.0
python scripts/sync_schema.py --from-npm latest
```

For an unreleased schema, pass a schema file with `--schema`; its provenance
records only the file name:

```bash
python scripts/sync_schema.py --schema mutations.graphql
```

Generated Python modules are committed to git. Update the schema or generator,
run `python scripts/codegen.py`, and commit the inputs and generated outputs
together.

## Development

See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, testing, and contribution
instructions.

## Wait for a Live URL handoff

```python
link = await page.live_url(instructions="Sign in, then click Done.", timeout=120_000)
print(link["liveURL"])
completion = await page.wait_for_live_complete(timeout=120_000)
if completion["reason"] != "userDone":
    raise RuntimeError(f"Handoff ended: {completion['reason']}")
# To cancel a link instead: await page.close_live_url(link["liveURLId"])
```

The sync facade uses the same calls without `await`.

For a richer human handoff, pass an instructions card:

```python
link = await page.live_url(
    instructions={
        "layout": "panel",
        "format": "markdown",
        "title": "Complete sign in",
        "summary": "**Sign in** to continue.",
        "steps": ["Open your inbox", "Enter the code"],
        "currentStep": 2,
    },
    done_label="Continue",
    fail_label="Need help",
    requester_name="Support",
)
```

With string instructions, use the top-level `instructions_title`, `steps`,
`current_step` and `instructions_format`. With a card, put `title`, `steps`,
`currentStep` and `format` inside it. Button labels and `requester_name` always
stay top-level. The server validates card limits. For an explicitly annotated
card, import `LiveURLInstructions` from `browserless_bap.types`.

The SDK subscribes before minting and retains completion until the next mint,
so a quick completion is not lost between `live_url()` and `wait_for_live_complete()`.
Wait timeouts are in milliseconds and raise `BAPTimeoutError`. By default
there is no client wait deadline; pass a positive timeout to bound the wait.
`timeout=0` also disables the wait deadline. Timing out or cancelling a wait does
not close the live URL.

Completion reasons are `userDone`, `userFailed`, `timeout`, `closed`, and
`viewerDisconnected`. Only `userDone` explicitly means the person finished.
Use `close_live_url(id)` to end a link programmatically;
the response contains `liveURLId`. Await each mint before starting another one.
A re-mint starts a new wait even when the server reuses its ID; existing waits
remain associated with the preceding handoff. Closing the page or losing the
connection rejects pending waits. The completion subscription closes when no pending handoffs or public listeners
remain; cached results remain available. Public listeners use `on`/`off`.
For reused IDs, the server emits the preceding handoff’s completion before the
replacement’s completion on the same ordered subscription stream.

Live URL handoffs need a Browserless server that supports
`wait_for_live_complete()` (the `liveComplete` event), `close_live_url()` and
instruction cards. When a live URL call passes `instructions`, this client sends
them in the newer format, which older servers reject even for a plain string.
Older clients send a format that newer servers reject. Upgrading is
therefore a coordinated client/server cutover, not a rolling server-first
upgrade.

For self-hosted upgrades, pause new handoffs and drain active ones, upgrade the
server and all clients together, then verify mint, completion, and close before
resuming handoffs. Handoffs remain unavailable during this cutover. To roll back,
pause and drain again and restore both the previous server and previous clients;
rolling back only one side leaves an incompatible pair. No mixed-version
compatibility path is provided by this SDK.
