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

from .helpers.http import build_api_headers, validate_api_credentials


def push_to_supover(
    session: requests.Session,
    url: str,
    api_key: str,
    payload: Any,
    timeout: int,
    api_key_header: str,
) -> requests.Response:
    """POST ``payload`` (the raw HMA response body) to the Supover sync endpoint."""
    key, target = validate_api_credentials(api_key, url, "SUPOVER_SYNC_URL")
    headers = build_api_headers(api_key_header, key)
    logging.info("POST %s — forwarding HMA response", target)
    return session.post(target, json=payload, headers=headers, timeout=timeout)
