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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

    from .config import Settings


@dataclass(frozen=True)
class SellerStatus:
    pending_settlement: str
    payout_on_hold: str
    bank_account_number: str | None
    shop_status: str | None
    all_elements_missing: bool


def _read_xpath(
    page: "Page", xpath: str, timeout: int, log: logging.Logger, field_name: str,
) -> tuple[str | None, bool]:
    """Return (text_content, found). found=False when element not visible within timeout."""
    try:
        locator = page.locator(f"xpath={xpath}")
        locator.wait_for(state="visible", timeout=timeout)
        return locator.text_content(), True
    except Exception:  # noqa: BLE001
        log.warning("Failed to read %s element.", field_name)
        return None, False


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
) -> SellerStatus:
    """Extract pending settlement, payout on hold, bank account number, and shop status."""
    timeout = settings.tiktok_element_timeout
    delay = settings.tiktok_step_delay

    if region == "GB":
        region = "uk"

    seller_login_url = settings.tiktok_seller_login_url.format(region=region)
    seller_bills_url = settings.tiktok_seller_bills_url.format(region=region)
    shop_info_api_url = settings.tiktok_shop_info_api_url.format(region=region)

    with _attach_to_profile(ws_url) as context:
        page = context.new_page()

        # TikTok keeps background requests open — networkidle often never fires.
        page.goto(seller_login_url, wait_until="load", timeout=timeout)
        login_wait = settings.tiktok_login_wait_seconds
        log.info(
            "Login page loaded; waiting %s s before checking for homepage redirect",
            login_wait,
        )
        time.sleep(login_wait)

        current_url = page.url
        saw_homepage = "homepage" in current_url
        if not saw_homepage:
            try:
                page.wait_for_url("**/homepage**", timeout=timeout)
                saw_homepage = True
            except Exception:  # noqa: BLE001
                pass
            current_url = page.url

        if not saw_homepage and "/account/login" in current_url:
            log.warning("Account not logged in — current URL: %s", current_url)
            return SellerStatus(
                pending_settlement="0",
                payout_on_hold="0",
                bank_account_number=None,
                shop_status=None,
                all_elements_missing=True,
            )

        log.info("Account is logged in — current URL before bills: %s", current_url)
        try:
            page.goto(seller_bills_url, wait_until="load")
        except Exception:  # noqa: BLE001
            log.warning("Bills page navigation interrupted; retrying in 10s (landed on %s)", page.url)
            time.sleep(10)
            page.goto(seller_bills_url, wait_until="load")

        pending_raw, pending_found = _read_xpath(page, settings.xpath_pending_balance, timeout, log, "pending_settlement")
        pending_settlement = pending_raw.replace("$", "").replace(",", "") if pending_raw else "0"
        time.sleep(delay)

        payout_raw, payout_found = _read_xpath(page, settings.xpath_on_hold, timeout, log, "payout_on_hold")
        payout_on_hold = payout_raw.replace("$", "").replace(",", "") if payout_raw else "0"
        time.sleep(delay)

        bank_raw, bank_found = _read_xpath(page, settings.xpath_bank_account, timeout, log, "bank_account_number")
        bank_account_number = bank_raw
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

        log.info(
            "pending_settlement=%s payout_on_hold=%s bank_account_number=%s shop_status=%s",
            pending_settlement,
            payout_on_hold,
            bank_account_number,
            shop_status,
        )

        return SellerStatus(
            pending_settlement=pending_settlement,
            payout_on_hold=payout_on_hold,
            bank_account_number=bank_account_number,
            shop_status=shop_status,
            all_elements_missing=not pending_found and not payout_found and not bank_found,
        )
