"""Scheduled job: nudge Supover to process pending HMA profiles.

Entry point invoked by Windows Task Scheduler once a day at 08:00. The
script fires a single ``GET`` to ``SUPOVER_PENDING_URL`` with the
``x-api-key: SUPOVER_API_KEY`` header so Supover can pick up and process
the rows the twice-daily sync (``scripts/sync_to_supover.py``) pushed in.

Trigger-only: the response body is logged as a short snippet, but not
parsed. Anything non-2xx exits with code 3 so Task Scheduler's "Last Run
Result" surfaces the failure.

Exit codes:
  0  success — Supover returned 2xx.
  1  configuration error (missing key / URL).
  3  Supover unreachable or returned non-2xx.

Logs go to stdout AND ``logs/supover_pending.log`` next to the project
root.

Run manually:
    python -m scripts.trigger_supover_pending
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import requests

# Make ``app.*`` importable when this script is launched with the project
# root as the working directory (the launcher .bat does ``cd %~dp0..``).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.hma_sync import setup_logging  # noqa: E402
from app.supover_sync import SUPOVER_API_KEY_HEADER  # noqa: E402

LOG_FILE = PROJECT_ROOT / "logs" / "supover_pending.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_SUPOVER = 3

_BODY_SNIPPET_CHARS = 500


def main() -> int:
    settings = get_settings()
    setup_logging(log_file=LOG_FILE, level=settings.hma_log_level)
    log = logging.getLogger("trigger_supover_pending")

    if not settings.supover_api_key.strip():
        log.error("SUPOVER_API_KEY is not configured — aborting.")
        return EXIT_CONFIG

    url = settings.supover_pending_url.strip()
    if not url:
        log.error("SUPOVER_PENDING_URL is empty — aborting.")
        return EXIT_CONFIG

    headers = {
        SUPOVER_API_KEY_HEADER: settings.supover_api_key.strip(),
        "Accept": "application/json",
    }

    session = requests.Session()
    log.info("GET %s", url)
    started = time.monotonic()
    try:
        resp = session.get(url, headers=headers, timeout=settings.hma_http_timeout)
    except requests.RequestException as exc:
        log.error("Supover /pending unreachable: %s", exc)
        return EXIT_SUPOVER

    elapsed = time.monotonic() - started
    snippet = (resp.text or "")[:_BODY_SNIPPET_CHARS]

    if not (200 <= resp.status_code < 300):
        log.error(
            "Supover /pending returned HTTP %s (%.2fs): %s",
            resp.status_code,
            elapsed,
            snippet,
        )
        return EXIT_SUPOVER

    log.info(
        "Supover /pending acknowledged (HTTP %s, %.2fs): %s",
        resp.status_code,
        elapsed,
        snippet,
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
