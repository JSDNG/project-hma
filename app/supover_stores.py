"""Pull dead-with-balance stores from the Supover HMA API.

Pure helpers: callers pass in the HTTP session, base URL, API key, and
timeout. The module performs no environment access of its own.

The Supover endpoint returns a paginated payload whose ``data`` field is a
list of stores; every store carries a nested ``profile_hma`` object with the
HideMyAcc profile metadata (id, profile_id, proxy, ...). The
``open_first_dead_store_youtube`` script uses ``profile_id`` to start the
profile against the local HMA REST API.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .supover_sync import SUPOVER_API_KEY_HEADER


def fetch_dead_stores_with_balance(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
    page: int = 1,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """GET ``url?page=&limit=`` against Supover's dead-with-balance endpoint.

    Returns the ``data`` array of store rows (may be empty). Raises
    ``ValueError`` for empty key/url or an unexpected response shape;
    ``requests.RequestException`` propagates for transport errors.
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("SUPOVER_API_KEY is not configured; refusing to GET")

    target = (url or "").strip()
    if not target:
        raise ValueError("SUPOVER_DEAD_STORES_URL is empty; refusing to GET")

    headers = {
        SUPOVER_API_KEY_HEADER: key,
        "Accept": "application/json",
    }
    params = {"page": page, "limit": limit}
    logging.info("GET %s params=%s", target, params)
    resp = session.get(target, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()

    try:
        body: Any = resp.json()
    except ValueError as exc:
        raise ValueError(
            f"Supover dead-with-balance returned non-JSON body: "
            f"{(resp.text or '')[:200]}"
        ) from exc

    envelope = _unwrap_envelope(body)
    data = envelope.get("data")
    if not isinstance(data, list):
        raise ValueError(
            f"Supover dead-with-balance: 'data' is not a list "
            f"(got {type(data).__name__})"
        )

    logging.info(
        "Supover dead-with-balance: page=%s total=%s returned=%d",
        envelope.get("page"),
        envelope.get("total"),
        len(data),
    )
    return data


def first_profile_id(stores: list[dict[str, Any]]) -> str:
    """Return the first non-empty ``profile_hma.profile_id`` from ``stores``.

    Raises ``LookupError`` if no row has a usable profile id.
    """
    for store in stores:
        profile_hma = store.get("profile_hma")
        if not isinstance(profile_hma, dict):
            continue
        pid = profile_hma.get("profile_id")
        if isinstance(pid, str) and pid.strip():
            return pid.strip()
    raise LookupError("No store carries a non-empty profile_hma.profile_id")


def _unwrap_envelope(body: Any) -> dict[str, Any]:
    """Return the paginated envelope, tolerating list-of-one wrapping.

    The endpoint currently returns ``[{...}]`` (per upstream screenshot), but
    a bare ``{...}`` is also accepted so a future shape tweak does not break
    callers silently.
    """
    if isinstance(body, list):
        if len(body) != 1 or not isinstance(body[0], dict):
            raise ValueError(
                "Supover dead-with-balance: expected a single envelope object "
                f"in the response list, got {body!r}"
            )
        return body[0]
    if isinstance(body, dict):
        return body
    raise ValueError(
        f"Supover dead-with-balance: unexpected top-level type "
        f"{type(body).__name__}"
    )
