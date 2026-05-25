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



def check_seller_status(
    ws_url: str, log: logging.Logger, settings: "Settings", region: str = "us",
) -> dict[str, str | None]:
    """Extract pending settlement, payout on hold, bank account number, and shop status.

    Returns a dict with keys: pending_settlement, payout_on_hold, bank_account_number,
    shop_status. Values are ``None`` when the element was not found.
    """
    timeout = settings.tiktok_element_timeout
    delay = settings.tiktok_step_delay

    seller_bills_url = settings.tiktok_seller_bills_url.format(region=region)
    shop_info_api_url = settings.tiktok_shop_info_api_url.format(region=region)

    with _attach_to_profile(ws_url) as context:
        page = context.new_page()

        page.goto(seller_bills_url, wait_until="domcontentloaded")

        pending_settlement: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_pending_balance}")
            locator.wait_for(state="visible", timeout=timeout)
            pending_settlement = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        payout_on_hold: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_on_hold}")
            locator.wait_for(state="visible", timeout=timeout)
            payout_on_hold = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        bank_account_number: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_bank_account}")
            locator.wait_for(state="visible", timeout=timeout)
            bank_account_number = locator.text_content()
        except Exception:  # noqa: BLE001
            pass

        time.sleep(delay)

        shop_status: str | None = None
        try:
            resp = page.evaluate(
                """async (url) => {
                    const r = await fetch(url);
                    return await r.json();
                }""",
                shop_info_api_url,
            )
            value = (resp.get("data") or {}).get("seller", {}).get("shop_status")
            if value is not None:
                shop_status = str(value)
        except Exception:  # noqa: BLE001
            log.warning("Shop info API call failed: url=%s", shop_info_api_url)

        time.sleep(delay)

        result = {
            "pending_settlement": pending_settlement,
            "payout_on_hold": payout_on_hold,
            "bank_account_number": bank_account_number,
            "shop_status": shop_status,
        }

        log.info(
            "pending_settlement=%s payout_on_hold=%s bank_account_number=%s shop_status=%s",
            pending_settlement,
            payout_on_hold,
            bank_account_number,
            shop_status,
        )

        return result
