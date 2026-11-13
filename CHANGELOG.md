# Changelog

## [0.3.0](https://github.com/browserless/bap-py/compare/v0.2.0...v0.3.0) (2026-11-13)


### ⚠ BREAKING CHANGES

* `Page.query_selector()` and `Page.query_selector_all()` no longer fetch `innerHTML`/`outerHTML`; pass `html=True`. Reading `ElementHandle.inner_html` or `outer_html` on a handle queried without it raises `BAPValueError`. `Page.response()` no longer returns `body`; pass `body=True` (or `body_encoding=True`, which implies it). the exceptions `TimeoutError`, `ConnectionError` and `ValueError` are removed from `browserless_bap` and `browserless_bap.errors`; use `BAPTimeoutError`, `BAPConnectionError` and `BAPValueError` (they still subclass the matching built-in exceptions). `browserless_bap.graphql.RESPONSE_FIELDS` no longer has the `HTTPResponseWithRemoteMetadata` and `ResponseResponseWithBodyEncoding` keys; use `OPTIONAL_FIELDS` with `selection_for()`. `QuerySelectorResponse["childElementCount"]` is typed `int` (was `float`), and `browserless_bap.sync_api.Browserless.connect(transport=...)` is typed `TransportFactory | None` (was `Any`).
* Opening a page now times out after `connect_timeout` (default: the `timeout` value, 30000 ms). Pass `connect_timeout=0` to restore the previous unbounded wait.

### Features

* bound connection time and harden the transport ([#9](https://github.com/browserless/bap-py/issues/9)) ([1689f3b](https://github.com/browserless/bap-py/commit/1689f3b77015edfad3a01f36e171955125cf9dc2))
* make element HTML and response bodies opt-in and rename builtin-shadowing errors ([#8](https://github.com/browserless/bap-py/issues/8)) ([bc80671](https://github.com/browserless/bap-py/commit/bc8067120d6fb981edee39862859a898cb070c9b))


### Bug Fixes

* encode element handle selectors so nested and special-character queries work ([#6](https://github.com/browserless/bap-py/issues/6)) ([f22f12b](https://github.com/browserless/bap-py/commit/f22f12b0ec13fa3d993e9ff0f9ae4757931484a0))
* sync API listener delivery, wait_for_function predicates and parity checks ([#7](https://github.com/browserless/bap-py/issues/7)) ([e5a106d](https://github.com/browserless/bap-py/commit/e5a106d0dc4414284b912e28593aebef1dab4351))

## 0.2.0 (2026-11-13)

First release on PyPI: `pip install browserless-bap`.
