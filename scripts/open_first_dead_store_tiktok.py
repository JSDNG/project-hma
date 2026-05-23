"""Smoke-test: run a browser action in the first dead-with-balance HMA profile.

Flow:

1. ``GET`` Supover ``SUPOVER_DEAD_STORES_URL?page=1&limit=100``.
2. Pick the first row whose ``profile_hma.profile_id`` is non-empty.
3. ``POST`` local HMA ``/profiles/start/{profile_id}`` and validate the
   response shape; extract ``data.wsUrl``.
4. Delegate the browser-side action to ``app.profile_actions`` — currently
   ``open_seller_bills`` (TikTok Seller US bills page).
5. Hold the browser open for 5 minutes (configurable via DWELL_SECONDS).
6. ``POST`` local HMA ``/profiles/stop/{profile_id}`` to close the profile.

To change what runs inside the browser, edit ``app/profile_actions.py``
(or swap the function called below) — this orchestration script stays
agnostic to the action.

The HMA stop call is always attempted, even when the action raised or the
dwell was interrupted by Ctrl+C, so we never leave an orphan profile.

Exit codes (Task Scheduler "Last Run Result"-friendly):
  0  success — action ran and the profile stopped cleanly.
  1  configuration error (missing key / base URL).
  2  Supover unreachable / bad response / no eligible profile.
  3  local HMA /profiles/start failed or returned a bad response.
  4  Playwright connect or navigation error inside the action.

Run manually:
    python -m scripts.open_first_dead_store_tiktok
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
from app.hma_sync import (  # noqa: E402
    interpret_start_response,
    setup_logging,
    start_profile,
    stop_profile,
)
from app.profile_actions import check_seller_status  # noqa: E402
from app.supover_stores import (  # noqa: E402
    fetch_dead_stores_with_balance,
    first_profile_id,
)

LOG_FILE = PROJECT_ROOT / "logs" / "open_first_dead_store_tiktok.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_SUPOVER = 2
EXIT_HMA = 3
EXIT_PLAYWRIGHT = 4


def main() -> int:
    settings = get_settings()
    setup_logging(log_file=LOG_FILE, level=settings.hma_log_level)
    log = logging.getLogger("open_first_dead_store_tiktok")

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
            page=1,
            limit=100,
        )
    except requests.RequestException as exc:
        log.error("Supover endpoint unreachable: %s", exc)
        return EXIT_SUPOVER
    except ValueError as exc:
        log.error("Supover returned an invalid body: %s", exc)
        return EXIT_SUPOVER

    try:
        profile_id = first_profile_id(stores)
    except LookupError as exc:
        log.error("%s", exc)
        return EXIT_SUPOVER

    log.info("Selected profile_id=%s", profile_id)

    try:
        start_resp = start_profile(
            session,
            settings.hma_local_api_base,
            profile_id,
            settings.hma_http_timeout,
        )
    except requests.RequestException as exc:
        log.error("Local HMA /profiles/start unreachable: %s", exc)
        return EXIT_HMA

    result = interpret_start_response(start_resp)
    if not result.ok:
        log.error("HMA /profiles/start failed: %s", result.error)
        return EXIT_HMA

    assert result.ws_url is not None
    log.info(
        "HMA profile started: port=%s majorVersion=%s wsUrl=%s",
        result.port,
        result.major_version,
        result.ws_url,
    )

    exit_code = EXIT_OK
    try:
        try:
            check_seller_status(result.ws_url, log)
        except KeyboardInterrupt:
            log.info("Interrupted by user; stopping profile early.")
        except Exception as exc:  # noqa: BLE001 — playwright raises broad types
            log.error("Playwright error: %s", exc)
            exit_code = EXIT_PLAYWRIGHT
    finally:
        try:
            stop_resp = stop_profile(
                session,
                settings.hma_local_api_base,
                profile_id,
                settings.hma_http_timeout,
            )
            if not (200 <= stop_resp.status_code < 300):
                log.warning(
                    "HMA /profiles/stop returned HTTP %s: %s",
                    stop_resp.status_code,
                    (stop_resp.text or "")[:300],
                )
            else:
                log.info("HMA profile stopped (HTTP %s).", stop_resp.status_code)
        except requests.RequestException as exc:
            log.warning("HMA /profiles/stop unreachable: %s", exc)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
