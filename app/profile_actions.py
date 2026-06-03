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

        # TikTok can redirect/reload several times after login. Observe URL transitions
        # for up to `timeout` and treat it as logged-in as soon as homepage appears.
        redirect_deadline = time.monotonic() + (timeout / 1000)
        current_url = page.url
        last_url = current_url
        saw_homepage = "homepage" in current_url

        while time.monotonic() < redirect_deadline and not saw_homepage:
            try:
                page.wait_for_load_state("load", timeout=1000)
            except Exception:  # noqa: BLE001
                pass

            current_url = page.url
            if current_url != last_url:
                log.info("Observed login redirect URL: %s", current_url)
                last_url = current_url
            saw_homepage = "homepage" in current_url
            if saw_homepage:
                break

            time.sleep(0.5)

        if not saw_homepage and "/account/login" in current_url:
            log.warning("Account not logged in — current URL: %s", current_url)
            return {
                "pending_settlement": "0",
                "payout_on_hold": "0",
                "bank_account_number": None,
                "shop_status": None,
                "all_elements_missing": True,
            }

        log.info("Account is logged in — current URL before bills: %s", current_url)
        try:
            page.goto(seller_bills_url, wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            # TikTok may interrupt navigation with a redirect (e.g. setup_fallback).
            # Wait for whatever page landed and let element reads fail gracefully below.
            log.warning("Bills page navigation interrupted; landed on %s", page.url)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=timeout)
            except Exception:  # noqa: BLE001
                pass

        pending_found = False
        pending_settlement: str = "0"
        try:
            locator = page.locator(f"xpath={settings.xpath_pending_balance}")
            locator.wait_for(state="visible", timeout=timeout)
            text = locator.text_content()
            if text:
                pending_settlement = text.replace("$", "").replace(",", "")
            pending_found = True
        except Exception:  # noqa: BLE001
            log.warning("Failed to read pending_settlement element.")

        time.sleep(delay)

        payout_found = False
        payout_on_hold: str = "0"
        try:
            locator = page.locator(f"xpath={settings.xpath_on_hold}")
            locator.wait_for(state="visible", timeout=timeout)
            text = locator.text_content()
            if text:
                payout_on_hold = text.replace("$", "").replace(",", "")
            payout_found = True
        except Exception:  # noqa: BLE001
            log.warning("Failed to read payout_on_hold element.")

        time.sleep(delay)

        bank_found = False
        bank_account_number: str | None = None
        try:
            locator = page.locator(f"xpath={settings.xpath_bank_account}")
            locator.wait_for(state="visible", timeout=timeout)
            bank_account_number = locator.text_content()
            bank_found = True
        except Exception:  # noqa: BLE001
            log.warning("Failed to read bank_account_number element.")

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
            "all_elements_missing": not pending_found and not payout_found and not bank_found,
        }

        log.info(
            "pending_settlement=%s payout_on_hold=%s bank_account_number=%s shop_status=%s",
            pending_settlement,
            payout_on_hold,
            bank_account_number,
            shop_status,
        )

        return result
