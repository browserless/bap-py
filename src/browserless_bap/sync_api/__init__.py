"""Blocking API for BAP.

Use this module when application code is synchronous::

    import browserless_bap.sync_api as bap

    with bap.Browserless.connect(browser_ws_endpoint=URL, token=TOKEN) as browser:
        with browser.page() as page:
            page.goto("https://example.com")
"""

from ._bridge import shutdown
from .browser import Browser
from .browserless import Browserless
from .element_handle import ElementHandle
from .page import Page

__all__ = [
    "Browser",
    "Browserless",
    "ElementHandle",
    "Page",
    "shutdown",
]
