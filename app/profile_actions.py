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

SELLER_BILLS_URL = "https://seller-us.tiktok.com/finance/bills"
HEALTH_CENTER_URL = "https://seller-us.tiktok.com/health-center"

PENDING_BALANCE_XPATH = "//div/div/div[3]/div/div[2]/div/div[1]/div/div/div/div[1]/div/div/div[1]/div[1]/div[2]/span"
BANK_ACCOUNT_XPATH = "//div[1]/div[2]/main/div/div/div[3]/div/div[2]/div/div[1]/div/div/div/div[2]/div/div/div/div[2]/div/div[2]/div/span[2]"
ACCOUNT_STATUS_XPATH = "//div[1]/section/nav/div/div/div/div/div/div/div[1]/div[1]/div[2]"


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


def check_seller_status(ws_url: str, log: logging.Logger) -> None:
    """Extract pending balance and account status from a TikTok Seller profile.

    1. Navigate to the bills page and read the pending balance.
    2. Navigate to the health-center page and check for "Account deactivated".
    3. Log both results, then dwell for 300 seconds.
    """
    with _attach_to_profile(ws_url) as context:
        page = context.new_page()

        # --- Bills page: pending balance ---
        page.goto(SELLER_BILLS_URL, wait_until="domcontentloaded")
        log.info("Seller bills loaded: url=%s", page.url)

        pending_balance: str | None = None
        try:
            locator = page.locator(f"xpath={PENDING_BALANCE_XPATH}")
            locator.wait_for(state="visible", timeout=15_000)
            pending_balance = locator.text_content()
        except Exception:  # noqa: BLE001
            log.warning("Pending balance element not found on bills page.")

        time.sleep(5)

        # --- Bills page: bank account ---
        bank_account: str | None = None
        try:
            locator = page.locator(f"xpath={BANK_ACCOUNT_XPATH}")
            locator.wait_for(state="visible", timeout=15_000)
            bank_account = locator.text_content()
        except Exception:  # noqa: BLE001
            log.warning("Bank account element not found on bills page.")

        time.sleep(5)

        # --- Health-center page: account status ---
        page.goto(HEALTH_CENTER_URL, wait_until="domcontentloaded")
        log.info("Health center loaded: url=%s", page.url)

        account_status: str | None = None
        try:
            locator = page.locator(f"xpath={ACCOUNT_STATUS_XPATH}")
            locator.wait_for(state="visible", timeout=15_000)
            text = (locator.text_content() or "").strip()
            if text == "Account deactivated":
                account_status = text
        except Exception:  # noqa: BLE001
            log.warning("Account status element not found on health-center page.")

        time.sleep(5)

        log.info(
            "pending_balance=%s bank_account=%s account_status=%s",
            pending_balance,
            bank_account,
            account_status,
        )

        time.sleep(300)
