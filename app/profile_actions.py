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
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext

    from .config import Settings


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


def open_seller_bills(ws_url: str, log: logging.Logger, settings: "Settings") -> None:
    """Open the TikTok Seller US bills page in a new tab on the HMA profile."""
    with _attach_to_profile(ws_url) as context:
        page = context.new_page()
        page.goto(settings.tiktok_seller_bills_url, wait_until="domcontentloaded")
        log.info(
            "Seller bills loaded: title=%r url=%s", page.title(), page.url
        )


def check_seller_status(
    ws_url: str, log: logging.Logger, settings: "Settings",
) -> dict[str, str | None]:
    """Extract pending balance, on-hold, bank account, and account status.

    Returns a dict with keys: pending_balance, on_hold, bank_account,
    account_status. Values are ``None`` when the element was not found.
    """
    timeout = settings.tiktok_element_timeout
    delay = settings.tiktok_step_delay

    with _attach_to_profile(ws_url) as context:
        page = context.new_page()

        page.goto(settings.tiktok_seller_bills_url, wait_until="domcontentloaded")
        log.info("Seller bills loaded: url=%s", page.url)

        pending_balance: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_pending_balance}")
            locator.wait_for(state="visible", timeout=timeout)
            pending_balance = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        on_hold: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_on_hold}")
            locator.wait_for(state="visible", timeout=timeout)
            on_hold = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        bank_account: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_bank_account}")
            locator.wait_for(state="visible", timeout=timeout)
            bank_account = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        page.goto(settings.tiktok_health_center_url, wait_until="domcontentloaded")
        log.info("Health center loaded: url=%s", page.url)

        account_status: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_account_status}")
            locator.wait_for(state="visible", timeout=timeout)
            text = (locator.text_content() or "").strip()
            if text == settings.tiktok_account_deactivated_text:
                account_status = text
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        result = {
            "pending_balance": pending_balance,
            "on_hold": on_hold,
            "bank_account": bank_account,
            "account_status": account_status,
        }

        log.info(
            "pending_balance=%s on_hold=%s bank_account=%s account_status=%s",
            pending_balance,
            on_hold,
            bank_account,
            account_status,
        )

        return result
