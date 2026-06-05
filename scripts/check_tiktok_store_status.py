"""Check TikTok store status for dead-with-balance HMA profiles.

Flow:

1. ``GET`` Supover ``SUPOVER_DEAD_STORES_URL?page=1&limit=N``.
2. For each eligible store (has ``store_id`` and ``profile_hma.profile_id``):
   a. ``POST`` local HMA ``/profiles/start/{profile_id}`` → extract ``wsUrl``.
   b. Navigate to TikTok Seller bills & health-center pages, extract data.
   c. ``POST`` extracted data back to Supover via ``/api/hma/stores/sync``.
   d. Dwell for ``TIKTOK_DWELL_SECONDS``.
   e. ``POST`` local HMA ``/profiles/stop/{profile_id}`` — always attempted.

The HMA stop call is always attempted per profile, even when the action
raised or the dwell was interrupted by Ctrl+C.

Exit codes (Task Scheduler "Last Run Result"-friendly):
  0  success — all profiles processed without error.
  1  configuration error (missing key / base URL).
  2  Supover unreachable / bad response / no eligible profile.
  3  local HMA /profiles/start failed (at least once).
  4  Playwright connect or navigation error (at least once).
  5  element read failure (at least once) — aborts remaining stores.
  6  not logged in (at least once) — skips store, continues to next.
  7  proxy dead (at least once) — skips store, continues to next.

Run manually:
    python -m scripts.check_tiktok_store_status
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.helpers.logging import setup_logging  # noqa: E402
from app.hma_sync import (  # noqa: E402
    interpret_start_response,
    start_profile,
    stop_profile,
)
from app.helpers.telegram import send_telegram_message  # noqa: E402
from app.profile_actions import check_seller_status  # noqa: E402
from app.supover_stores import (  # noqa: E402
    all_store_and_profile_ids,
    fetch_dead_stores_with_balance,
    push_store_status,
)

LOG_FILE = PROJECT_ROOT / "logs" / "check_tiktok_store_status.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_SUPOVER = 2
EXIT_HMA = 3
EXIT_PLAYWRIGHT = 4
EXIT_ELEMENT_READ = 5
EXIT_NOT_LOGGED_IN = 6
EXIT_PROXY_DEAD = 7

PROXY_TEST_URL = "https://api.ipify.org?format=json"
PROXY_TEST_TIMEOUT = 60
PROXY_CHECK_DWELL_SECONDS = 60


def _check_proxy_alive(
    host: str, port: int | None, username: str, password: str,
) -> tuple[bool, str | None]:
    """GET ``PROXY_TEST_URL`` through ``host:port``. Return (alive, error)."""
    if not host or not port:
        return False, "proxy host/port missing"
    auth = f"{username}:{password}@" if username and password else ""
    proxy_url = f"http://{auth}{host}:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        resp = requests.get(PROXY_TEST_URL, proxies=proxies, timeout=PROXY_TEST_TIMEOUT)
    except requests.RequestException as exc:
        return False, str(exc)
    if not (200 <= resp.status_code < 300):
        return False, f"HTTP {resp.status_code}"
    return True, None


def _process_store(
    session: requests.Session,
    settings,
    log: logging.Logger,
    store_id: int,
    store_name: str,
    tt_shop_code: str,
    region: str,
    profile_id: str,
    profile_name: str,
    proxy_host: str,
    proxy_port: int | None,
    proxy_username: str,
    proxy_password: str,
    seller: str,
    telegram: str,
) -> int:
    """Start profile, check status, push to Supover, dwell, stop. Return exit code."""
    if proxy_host:
        log.info("Testing proxy %s:%s for profile_id=%s", proxy_host, proxy_port, profile_id)
        alive, proxy_error = _check_proxy_alive(
            proxy_host, proxy_port, proxy_username, proxy_password,
        )
        if not alive:
            log.error(
                "Proxy dead for store_id=%s profile_id=%s (%s:%s): %s",
                store_id, profile_id, proxy_host, proxy_port, proxy_error,
            )
            try:
                push_store_status(
                    session,
                    settings.supover_stores_sync_url,
                    settings.supover_api_key,
                    settings.hma_http_timeout,
                    settings.supover_api_key_header,
                    store_id=store_id,
                    tt_shop_code=tt_shop_code,
                    profile_id=profile_id,
                    region=region,
                    pending_settlement=None,
                    payout_on_hold=None,
                    bank_account_number=None,
                    shop_status=None,
                    error="Proxy dead",
                )
            except (requests.RequestException, ValueError) as exc:
                log.error("Supover stores/sync failed (proxy dead notify): %s", exc)
            time.sleep(PROXY_CHECK_DWELL_SECONDS)
            return EXIT_PROXY_DEAD
        log.info("Proxy alive — sleeping %ss", PROXY_CHECK_DWELL_SECONDS)
        time.sleep(PROXY_CHECK_DWELL_SECONDS)

    try:
        start_resp = start_profile(
            session,
            settings.hma_local_api_base,
            profile_id,
            settings.hma_http_timeout,
            settings.hma_profiles_path,
        )
    except requests.RequestException as exc:
        log.error("Local HMA /profiles/start unreachable: %s", exc)
        return EXIT_HMA

    result = interpret_start_response(start_resp, settings.hma_start_success_code)
    if not result.ok:
        log.error("HMA /profiles/start failed: %s", result.error)
        try:
            push_store_status(
                session,
                settings.supover_stores_sync_url,
                settings.supover_api_key,
                settings.hma_http_timeout,
                settings.supover_api_key_header,
                store_id=store_id,
                tt_shop_code=tt_shop_code,
                profile_id=profile_id,
                region=region,
                pending_settlement=None,
                payout_on_hold=None,
                bank_account_number=None,
                shop_status=None,
                error="HMA profile in use",
            )
        except (requests.RequestException, ValueError) as exc:
            log.error("Supover stores/sync failed (profile-in-use notify): %s", exc)
        send_telegram_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            (
                f"<b>Tool HMA TikTok Profile In Use</b>\n"
                f"Store Name: {store_name} ({tt_shop_code})\n"
                f"Profile Name: {profile_name}\n"
                f"Seller: {seller}\n"
                f"Telegram: @{telegram.lstrip('@')}\n"
                f"Error: Cannot open profile — seller is currently using it (HMA: {result.error})"
            ),
        )
        return EXIT_HMA

    assert result.ws_url is not None

    exit_code = EXIT_OK
    try:
        try:
            status_data = check_seller_status(result.ws_url, log, settings, region)
        except KeyboardInterrupt:
            log.info("Interrupted by user; stopping profile early.")
        except Exception as exc:  # noqa: BLE001
            log.error("Playwright error: %s", exc)
            send_telegram_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                (
                    f"<b>Tool HMA TikTok Playwright Error</b>\n"
                    f"Store Name: {store_name} ({tt_shop_code})\n"
                    f"Profile Name: {profile_name}\n"
                    f"Seller: {seller}\n"
                    f"Telegram: @{telegram.lstrip('@')}\n"
                    f"Error: Cannot reach TikTok seller page\n"
                    f"Details: {exc}"
                ),
            )
            exit_code = EXIT_PLAYWRIGHT
        else:
            all_elements_missing = status_data.pop("all_elements_missing", False)

            if all_elements_missing:
                log.warning(
                    "All elements missing (likely not logged in) for store_id=%s shop_code=%s profile_id=%s",
                    store_id, tt_shop_code, profile_id,
                )
                try:
                    push_store_status(
                        session,
                        settings.supover_stores_sync_url,
                        settings.supover_api_key,
                        settings.hma_http_timeout,
                        settings.supover_api_key_header,
                        store_id=store_id,
                        tt_shop_code=tt_shop_code,
                        profile_id=profile_id,
                        region=region,
                        pending_settlement=None,
                        payout_on_hold=None,
                        bank_account_number=None,
                        shop_status=None,
                        error="TikTok not logged in",
                    )
                except (requests.RequestException, ValueError) as exc:
                    log.error("Supover stores/sync failed (not-logged-in notify): %s", exc)
                exit_code = EXIT_NOT_LOGGED_IN
            else:
                if status_data["bank_account_number"] is None:
                    log.warning(
                        "bank_account_number not found for store_id=%s shop_code=%s — continuing.",
                        store_id, tt_shop_code,
                    )

                errors: list[str] = []
                if status_data["pending_settlement"] == "0" and status_data["payout_on_hold"] == "0":
                    errors.append("pending_settlement and payout_on_hold both returned '0'")
                if status_data["shop_status"] is None:
                    errors.append("shop_status API returned no data")

                if errors:
                    error_detail = "; ".join(errors)
                    log.error(
                        "Element read error for store_id=%s shop_code=%s profile_id=%s: %s",
                        store_id, tt_shop_code, profile_id, error_detail,
                    )
                    send_telegram_message(
                        settings.telegram_bot_token,
                        settings.telegram_chat_id,
                        (
                            f"<b>Tool HMA TikTok Element Read Error</b>\n"
                            f"Store Name: {store_name} ({tt_shop_code})\n"
                            f"Profile Name: {profile_name}\n"
                            f"Seller: {seller}\n"
                            f"Telegram: @{telegram.lstrip('@')}\n"
                            f"Error: {error_detail}"
                        ),
                    )
                    exit_code = EXIT_ELEMENT_READ
                else:
                    try:
                        sync_resp = push_store_status(
                            session,
                            settings.supover_stores_sync_url,
                            settings.supover_api_key,
                            settings.hma_http_timeout,
                            settings.supover_api_key_header,
                            store_id=store_id,
                            tt_shop_code=tt_shop_code,
                            profile_id=profile_id,
                            region=region,
                            **status_data,
                        )
                        log.info(
                            "Supover stores/sync responded HTTP %s: %s",
                            sync_resp.status_code,
                            (sync_resp.text or "")[:300],
                        )
                    except (requests.RequestException, ValueError) as exc:
                        log.error("Supover stores/sync failed: %s", exc)

            if exit_code == EXIT_OK:
                try:
                    time.sleep(settings.tiktok_dwell_seconds)
                except KeyboardInterrupt:
                    log.info("Dwell interrupted by user; stopping profile early.")
            else:
                log.info(
                    "Skipping dwell because store ended with exit_code=%s.",
                    exit_code,
                )
    finally:
        try:
            stop_resp = stop_profile(
                session,
                settings.hma_local_api_base,
                profile_id,
                settings.hma_http_timeout,
                settings.hma_profiles_path,
            )
            if not (200 <= stop_resp.status_code < 300):
                log.warning(
                    "HMA /profiles/stop returned HTTP %s: %s",
                    stop_resp.status_code,
                    (stop_resp.text or "")[:300],
                )
        except requests.RequestException as exc:
            log.warning("HMA /profiles/stop unreachable: %s", exc)

    return exit_code


def main() -> int:
    settings = get_settings()
    setup_logging(log_file=LOG_FILE, level=settings.hma_log_level)
    log = logging.getLogger("check_tiktok_store_status")

    if not settings.supover_api_key.strip():
        log.error("SUPOVER_API_KEY is not configured — aborting.")
        return EXIT_CONFIG
    if not settings.supover_dead_stores_url.strip():
        log.error("SUPOVER_DEAD_STORES_URL is empty — aborting.")
        return EXIT_CONFIG

    session = requests.Session()

    try:
        stores = fetch_dead_stores_with_balance(
            session,
            settings.supover_dead_stores_url,
            settings.supover_api_key,
            settings.hma_http_timeout,
            settings.supover_api_key_header,
            page=1,
            limit=100,
        )
    except requests.RequestException as exc:
        log.error("Supover endpoint unreachable: %s", exc)
        return EXIT_SUPOVER
    except ValueError as exc:
        log.error("Supover returned an invalid body: %s", exc)
        return EXIT_SUPOVER

    pairs = all_store_and_profile_ids(stores)
    #pairs = pairs[6:]
    if not pairs:
        log.error("No eligible store with a non-empty profile_hma.profile_id.")
        return EXIT_SUPOVER

    log.info("Found %d eligible store(s) to process.", len(pairs))

    worst_code = EXIT_OK
    for i, store in enumerate(pairs, 1):
        log.info(
            "--- Store %d/%d: store_id=%s shop_code=%s region=%s profile_id=%s profile_name=%s ---",
            i, len(pairs), store.store_id, store.shop_code, store.region,
            store.profile_id, store.profile_name,
        )
        code = _process_store(
            session, settings, log,
            store.store_id, store.store_name, store.shop_code, store.region,
            store.profile_id, store.profile_name,
            store.proxy_host, store.proxy_port,
            store.proxy_username, store.proxy_password,
            store.seller, store.telegram,
        )
        if code > worst_code:
            worst_code = code
        if code == EXIT_ELEMENT_READ:
            log.error("Element read failure — aborting remaining stores.")
            break

    return worst_code


if __name__ == "__main__":
    raise SystemExit(main())
