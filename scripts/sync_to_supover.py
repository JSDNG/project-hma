"""Scheduled job: pull HMA profiles, forward raw response to Supover.

Entry point invoked by Windows Task Scheduler twice a day (00:00 and 12:00).
Standalone — does not require the FastAPI service to be running. The script:

1. Loads settings from .env (same file the API uses).
2. Calls the local HMA REST API at ``HMA_LOCAL_API_BASE`` directly.
3. POSTs HMA's ``/profiles`` response body unchanged to ``SUPOVER_SYNC_URL``
   with the ``x-api-key: SUPOVER_API_KEY`` header.

Exit codes (so Task Scheduler "Last Run Result" is meaningful):
  0  success — Supover accepted the payload (2xx).
  1  configuration error (missing key / URL).
  2  local HMA unreachable or returned a malformed body.
  3  Supover unreachable or returned non-2xx.

Logs go to stdout AND ``logs/supover_sync.log`` next to the project root.

Run manually:
    python -m scripts.sync_to_supover
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import requests

# Make ``app.*`` importable when this script is launched with the project
# root as the working directory (the launcher .bat does ``cd %~dp0..``).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.helpers.logging import setup_logging  # noqa: E402
from app.hma_sync import fetch_profiles_response  # noqa: E402
from app.supover_sync import push_to_supover  # noqa: E402

LOG_FILE = PROJECT_ROOT / "logs" / "supover_sync.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_HMA = 2
EXIT_SUPOVER = 3


def main() -> int:
    settings = get_settings()
    setup_logging(log_file=LOG_FILE, level=settings.hma_log_level)
    log = logging.getLogger("sync_to_supover")

    if not settings.supover_api_key.strip():
        log.error("SUPOVER_API_KEY is not configured — aborting.")
        return EXIT_CONFIG
    if not settings.supover_sync_url.strip():
        log.error("SUPOVER_SYNC_URL is empty — aborting.")
        return EXIT_CONFIG

    session = requests.Session()

    # 1) Pull the raw HMA /profiles response.
    try:
        payload = fetch_profiles_response(
            session, settings.hma_local_api_base, settings.hma_http_timeout,
            settings.hma_profiles_path,
        )
    except requests.RequestException as exc:
        log.error("Local HMA API unreachable: %s", exc)
        return EXIT_HMA
    except ValueError as exc:
        log.error("Local HMA API returned an invalid body: %s", exc)
        return EXIT_HMA

    # 2) Forward verbatim to Supover.
    try:
        resp = push_to_supover(
            session,
            settings.supover_sync_url,
            settings.supover_api_key,
            payload,
            settings.hma_http_timeout,
            settings.supover_api_key_header,
        )
    except ValueError as exc:
        log.error("Refusing to POST: %s", exc)
        return EXIT_CONFIG
    except requests.RequestException as exc:
        log.error("Supover endpoint unreachable: %s", exc)
        return EXIT_SUPOVER

    if not (200 <= resp.status_code < 300):
        snippet = (resp.text or "")[:500]
        log.error(
            "Supover returned HTTP %s: %s", resp.status_code, snippet
        )
        return EXIT_SUPOVER

    log.info("Supover accepted payload (HTTP %s).", resp.status_code)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
