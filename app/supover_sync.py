"""Outbound push of mapped HMA profile rows to the Supover sync endpoint.

Pure helpers, no FastAPI imports and no environment access — callers pass in
the URL, key, rows, and HTTP session. The scheduled runner in
``scripts/sync_to_supover.py`` is the only consumer today.

The payload shape mirrors what ``GET /profiles`` returns from this service
so the remote side sees one consistent contract regardless of who triggered
the sync::

    {
      "count": <int>,
      "data":  [<profile_row>, ...]
    }
"""

from __future__ import annotations

import logging
from typing import Any

import requests

DEFAULT_SUPOVER_URL = "https://ai.supover.com/api/profile-hma/sync"
SUPOVER_API_KEY_HEADER = "x-api-key"


def build_supover_payload(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Wrap mapped rows in the {count, data} envelope used by GET /profiles."""
    return {"count": len(rows), "data": rows}


def push_to_supover(
    session: requests.Session,
    url: str,
    api_key: str,
    rows: list[dict[str, str]],
    timeout: int,
) -> requests.Response:
    """POST mapped profile rows to the Supover sync endpoint.

    Raises ``ValueError`` when ``api_key`` is empty so the runner fail-closes
    instead of sending an unauthenticated request that would silently 401.
    Network errors propagate as ``requests.RequestException`` for the caller
    to handle.
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("SUPOVER_API_KEY is not configured; refusing to POST")

    target = (url or "").strip()
    if not target:
        raise ValueError("SUPOVER_SYNC_URL is empty; refusing to POST")

    headers = {
        SUPOVER_API_KEY_HEADER: key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = build_supover_payload(rows)
    logging.info("POST %s — %d row(s)", target, len(rows))
    return session.post(target, json=payload, headers=headers, timeout=timeout)
