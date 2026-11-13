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
| `eval_on_selector` | `text` | `str` | ✅ |
| `eval_on_selector_all` | `mapSelector` | `list[MapSelectorResponse]` | ✅ |
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

## Schema and generated code

`src/browserless_bap/mutations.graphql` is the vendored GraphQL schema. Its full digest,
line count, and source provenance are committed in `schema.lock`. Verify the
vendored schema without requiring any sibling checkout:

```bash
python scripts/sync_schema.py --check
```

By default, syncing reads the schema from a sibling checkout of the TypeScript
SDK (`../bap-ts/src/mutations.graphql`). Any schema file can be selected with
`--schema`, for example `src/mutations.graphql` from the `@browserless.io/bap-ts`
npm package:

```bash
python scripts/sync_schema.py --from-bap-ts
python scripts/sync_schema.py --schema /path/to/mutations.graphql
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
Wait timeouts are in milliseconds and raise the SDK `TimeoutError`. By default
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
instruction cards. This client always sends live URL instructions in the newer
format, which older servers reject even when the instructions are a plain
string, and older clients send a format that newer servers reject. Upgrading is
therefore a coordinated client/server cutover, not a rolling server-first
upgrade.

For self-hosted upgrades, pause new handoffs and drain active ones, upgrade the
server and all clients together, then verify mint, completion, and close before
resuming handoffs. Handoffs remain unavailable during this cutover. To roll back,
pause and drain again and restore both the previous server and previous clients;
rolling back only one side leaves an incompatible pair. No mixed-version
compatibility path is provided by this SDK.
