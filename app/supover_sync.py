"""Outbound push of the raw HMA profile response to the Supover sync endpoint.

Pure helpers, no FastAPI imports and no environment access — callers pass in
the URL, key, payload, and HTTP session. The scheduled runner in
``scripts/sync_to_supover.py`` is the only consumer today.

The payload is forwarded **verbatim** as whatever the local HMA
``GET /profiles`` API returned (typically ``{"code": ..., "data": [...]}``).
No mapping, no envelope re-shaping — Supover sees exactly what HMA sent.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

DEFAULT_SUPOVER_URL = "https://ai.supover.com/api/hma/profiles/sync"
SUPOVER_API_KEY_HEADER = "x-api-key"


def push_to_supover(
    session: requests.Session,
    url: str,
    api_key: str,
    payload: Any,
    timeout: int,
) -> requests.Response:
    """POST ``payload`` (the raw HMA response body) to the Supover sync endpoint.

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
    logging.info("POST %s — forwarding HMA response", target)
    return session.post(target, json=payload, headers=headers, timeout=timeout)
