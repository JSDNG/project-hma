"""Browser-side actions to run inside a started HMA profile.

Each action takes the CDP ``wsUrl`` returned by HMA's ``/profiles/start/{id}``,
attaches Playwright over CDP, performs its work, then disconnects. The
underlying Chromium process stays alive — HMA owns it; ``browser.close()``
only tears down the CDP session opened by this script.

Playwright is imported lazily inside the helpers so importing this module
does not require playwright to be installed (useful for CI / unit tests).

Add new actions here as standalone functions: keep the orchestration script
thin and put browser-side logic next to the URL constants it operates on.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext

SELLER_BILLS_URL = "https://seller-us.tiktok.com/finance/bills"


@contextmanager
def _attach_to_profile(ws_url: str) -> Iterator["BrowserContext"]:
    """Yield the HMA profile's first BrowserContext via CDP.

    Falls back to a fresh context only if the running profile somehow exposes
    none (HMA normally launches with a default context already attached).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_url)
        try:
            yield (
                browser.contexts[0] if browser.contexts else browser.new_context()
            )
        finally:
            browser.close()


def open_seller_bills(ws_url: str, log: logging.Logger) -> None:
    """Open the TikTok Seller US bills page in a new tab on the HMA profile."""
    with _attach_to_profile(ws_url) as context:
        page = context.new_page()
        page.goto(SELLER_BILLS_URL, wait_until="domcontentloaded")
        log.info(
            "Seller bills loaded: title=%r url=%s", page.title(), page.url
        )
