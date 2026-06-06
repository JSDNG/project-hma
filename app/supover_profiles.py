"""Pull the list of unused HMA profiles that Supover wants deleted.

Pure helpers: callers pass in the HTTP session, base URL, API key, and
timeout. The module performs no environment access of its own.

The Supover endpoint is paginated (``page``/``limit``/``total``) and wraps its
envelope in a single-element list::

    [ { "status": true, "page": 1, "limit": 1000, "total": 1234, "data": [ {row}, ... ] } ]

Each row carries ``profile_id``, ``profile_name`` and ``last_opened_at``.
``fetch_all_profiles_to_delete`` keeps fetching the next page while ``total``
exceeds what has been fetched (waiting 5s between pages) and returns the
combined raw rows; ``all_deletable_profiles`` then drops any row without a
usable ``profile_id``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, NamedTuple

import requests

from .helpers.http import build_api_headers, validate_api_credentials

PAGE_LIMIT = 1000
PAGE_FETCH_DELAY_SECONDS = 5


class DeletableProfile(NamedTuple):
    """An HMA profile Supover has flagged for deletion, validated."""

    profile_id: str
    profile_name: str
    last_opened_at: str


class ProfilePage(NamedTuple):
    """One page of the Supover delete-profiles response."""

    rows: list[dict[str, Any]]
    total: int


def fetch_profiles_to_delete(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
    api_key_header: str,
    page: int = 1,
    limit: int = PAGE_LIMIT,
) -> ProfilePage:
    """GET one page of Supover's profiles-to-delete endpoint.

    Returns a ``ProfilePage`` with the page's ``data`` rows and the envelope's
    ``total``. Raises ``ValueError`` for empty key/url or an unexpected
    response shape; ``requests.RequestException`` propagates for transport errors.
    """
    key, target = validate_api_credentials(api_key, url, "SUPOVER_DELETE_PROFILES_URL")
    headers = build_api_headers(api_key_header, key, include_content_type=False)
    params = {"page": page, "limit": limit}
    logging.info("GET %s params=%s", target, params)
    resp = session.get(target, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()

    try:
        body: Any = resp.json()
    except ValueError as exc:
        raise ValueError(
            f"Supover delete-profiles returned non-JSON body: "
            f"{(resp.text or '')[:200]}"
        ) from exc

    envelope = _unwrap_envelope(body)
    data = envelope.get("data")
    if not isinstance(data, list):
        raise ValueError(
            f"Supover delete-profiles: 'data' is not a list "
            f"(got {type(data).__name__})"
        )

    total_raw = envelope.get("total")
    total = total_raw if isinstance(total_raw, int) and total_raw > 0 else len(data)

    logging.info(
        "Supover delete-profiles: page=%s total=%s returned=%d",
        envelope.get("page"), total, len(data),
    )
    return ProfilePage(rows=data, total=total)


def fetch_all_profiles_to_delete(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
    api_key_header: str,
    limit: int = PAGE_LIMIT,
) -> list[dict[str, Any]]:
    """Walk every page of the delete-profiles endpoint, return all raw rows.

    Fetches ``page=1`` and, while ``total`` exceeds what has been fetched so
    far, increments ``page`` and fetches again — waiting
    ``PAGE_FETCH_DELAY_SECONDS`` before each subsequent request.
    """
    all_rows: list[dict[str, Any]] = []
    page = 1
    while True:
        result = fetch_profiles_to_delete(
            session, url, api_key, timeout, api_key_header, page=page, limit=limit,
        )
        all_rows.extend(result.rows)
        if not result.rows or page * limit >= result.total:
            break
        page += 1
        time.sleep(PAGE_FETCH_DELAY_SECONDS)
    return all_rows


def all_deletable_profiles(rows: list[dict[str, Any]]) -> list[DeletableProfile]:
    """Return one ``DeletableProfile`` per row with a valid ``profile_id``."""
    results: list[DeletableProfile] = []
    for row in rows:
        pid = row.get("profile_id")
        if not (isinstance(pid, str) and pid.strip()):
            continue
        results.append(
            DeletableProfile(
                profile_id=pid.strip(),
                profile_name=str(row.get("profile_name") or "").strip(),
                last_opened_at=str(row.get("last_opened_at") or "").strip(),
            )
        )
    return results


def _unwrap_envelope(body: Any) -> dict[str, Any]:
    """Return the envelope object, tolerating list-of-one wrapping."""
    if isinstance(body, list):
        if len(body) != 1 or not isinstance(body[0], dict):
            raise ValueError(
                "Supover delete-profiles: expected a single envelope object "
                f"in the response list, got {body!r}"
            )
        return body[0]
    if isinstance(body, dict):
        return body
    raise ValueError(
        f"Supover delete-profiles: unexpected top-level type "
        f"{type(body).__name__}"
    )
