"""Manual job: pull unused profiles from Supover, delete them on local HMA.

Standalone — does not require the FastAPI service to be running. The script:

1. Loads settings from .env (same file the API uses).
2. ``GET`` Supover ``SUPOVER_DELETE_PROFILES_URL?page=1&limit=100`` for the
   list of profiles to delete.
3. For each profile with a valid ``profile_id``, calls the local HMA
   ``DELETE /profiles/{id}`` API, waiting ``DELETE_INTERVAL_SECONDS`` between
   deletes so HMA is not hammered.

A single delete failure is logged and pushed to Telegram, then the run
continues with the remaining profiles. To avoid hammering a systemic outage
(HMA down, account not on a Team plan), the run aborts after
``MAX_CONSECUTIVE_FAILURES`` failures in a row with one summary Telegram, and
the local HMA API is pinged once up front so a dead HMA fails fast. Nothing is
reported back to Supover.

Exit codes (so Task Scheduler "Last Run Result" is meaningful):
  0  success — every profile deleted.
  1  configuration error (missing key / URL).
  2  Supover unreachable / bad response / nothing to delete.
  3  local HMA unreachable, or at least one profile failed to delete.

Logs go to stdout AND ``logs/delete_unused_profiles.log`` next to the project root.

Run manually:
    python -m scripts.delete_unused_profiles
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
from app.helpers.telegram import send_telegram_message  # noqa: E402
from app.hma_sync import (  # noqa: E402
    delete_profile,
    fetch_profiles_response,
    interpret_delete_response,
)
from app.supover_profiles import (  # noqa: E402
    all_deletable_profiles,
    fetch_all_profiles_to_delete,
)

LOG_FILE = PROJECT_ROOT / "logs" / "delete_unused_profiles.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_SUPOVER = 2
EXIT_HMA = 3

DELETE_INTERVAL_SECONDS = 5
MAX_CONSECUTIVE_FAILURES = 5


def _notify_failure(settings, profile, error: str) -> None:
    send_telegram_message(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        (
            f"<b>Tool HMA Delete Profile Failed</b>\n"
            f"Profile Name: {profile.profile_name}\n"
            f"Profile ID: {profile.profile_id}\n"
            f"Last Opened: {profile.last_opened_at}\n"
            f"Error: {error}"
        ),
    )


def main() -> int:
    settings = get_settings()
    setup_logging(log_file=LOG_FILE, level=settings.hma_log_level)
    log = logging.getLogger("delete_unused_profiles")

    if not settings.supover_api_key.strip():
        log.error("SUPOVER_API_KEY is not configured — aborting.")
        return EXIT_CONFIG
    if not settings.supover_delete_profiles_url.strip():
        log.error("SUPOVER_DELETE_PROFILES_URL is empty — aborting.")
        return EXIT_CONFIG

    session = requests.Session()

    # Fail fast: don't pull 1234 ids from Supover if HMA can't be reached.
    try:
        fetch_profiles_response(
            session, settings.hma_local_api_base, settings.hma_http_timeout,
            settings.hma_profiles_path,
        )
    except (requests.RequestException, ValueError) as exc:
        log.error("Local HMA API unreachable — aborting before any delete: %s", exc)
        return EXIT_HMA

    try:
        rows = fetch_all_profiles_to_delete(
            session,
            settings.supover_delete_profiles_url,
            settings.supover_api_key,
            settings.hma_http_timeout,
            settings.supover_api_key_header,
        )
    except requests.RequestException as exc:
        log.error("Supover endpoint unreachable: %s", exc)
        return EXIT_SUPOVER
    except ValueError as exc:
        log.error("Supover returned an invalid body: %s", exc)
        return EXIT_SUPOVER

    profiles = all_deletable_profiles(rows)
    if not profiles:
        log.error("No profile to delete with a valid profile_id.")
        return EXIT_SUPOVER

    est_minutes = (len(profiles) - 1) * DELETE_INTERVAL_SECONDS / 60
    log.info(
        "Found %d profile(s) to delete; ~%.1f min at %ds spacing.",
        len(profiles), est_minutes, DELETE_INTERVAL_SECONDS,
    )

    deleted = 0
    failed = 0
    consecutive_failures = 0
    total = len(profiles)
    for i, profile in enumerate(profiles, 1):
        log.info(
            "--- Delete %d/%d: profile_id=%s profile_name=%s last_opened_at=%s ---",
            i, total, profile.profile_id, profile.profile_name,
            profile.last_opened_at,
        )
        try:
            resp = delete_profile(
                session,
                settings.hma_local_api_base,
                profile.profile_id,
                settings.hma_http_timeout,
                settings.hma_profiles_path,
            )
        except requests.RequestException as exc:
            error = f"Local HMA /profiles DELETE unreachable: {exc}"
        else:
            _, error = interpret_delete_response(resp, settings.hma_delete_success_code)

        if error is None:
            deleted += 1
            consecutive_failures = 0
            log.info("Deleted profile_id=%s.", profile.profile_id)
        else:
            failed += 1
            consecutive_failures += 1
            log.error("Failed to delete profile_id=%s: %s", profile.profile_id, error)
            _notify_failure(settings, profile, error)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error(
                    "Aborting: %d consecutive failures at profile %d/%d — likely a "
                    "systemic issue (HMA down or no Team plan).",
                    consecutive_failures, i, total,
                )
                send_telegram_message(
                    settings.telegram_bot_token,
                    settings.telegram_chat_id,
                    (
                        f"<b>Tool HMA Delete Profiles Aborted</b>\n"
                        f"Stopped after {consecutive_failures} consecutive failures "
                        f"at profile {i}/{total}.\n"
                        f"Deleted: {deleted} · Failed: {failed}\n"
                        f"Last error: {error}"
                    ),
                )
                break

        if i < total:
            try:
                time.sleep(DELETE_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                log.info("Interrupted by user; stopping before remaining profiles.")
                break

    log.info("Done: deleted=%d failed=%d of %d.", deleted, failed, total)
    return EXIT_HMA if failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
