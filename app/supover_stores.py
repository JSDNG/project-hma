"""Pull dead-with-balance stores and push store status to the Supover HMA API.

Pure helpers: callers pass in the HTTP session, base URL, API key, and
timeout. The module performs no environment access of its own.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .helpers.http import build_api_headers, validate_api_credentials


def push_store_status(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
    api_key_header: str,
    *,
    store_id: int,
    tt_shop_code: str,
    profile_id: str,
    pending_settlement: str | None,
    payout_on_hold: str | None,
    bank_account_number: str | None,
    shop_status: str | None,
) -> requests.Response:
    """POST extracted seller status to the Supover stores sync endpoint."""
    key, target = validate_api_credentials(api_key, url, "SUPOVER_STORES_SYNC_URL")
    headers = build_api_headers(api_key_header, key)
    payload = {
        "store_id": store_id,
        "tt_shop_code": tt_shop_code,
        "profile_id": profile_id,
        "pending_settlement": pending_settlement,
        "payout_on_hold": payout_on_hold,
        "bank_account_number": bank_account_number,
        "shop_status": shop_status,
    }
    return session.post(target, json=payload, headers=headers, timeout=timeout)


def fetch_dead_stores_with_balance(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
    api_key_header: str,
    page: int = 1,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """GET ``url?page=&limit=`` against Supover's dead-with-balance endpoint.

    Returns the ``data`` array of store rows (may be empty). Raises
    ``ValueError`` for empty key/url or an unexpected response shape;
    ``requests.RequestException`` propagates for transport errors.
    """
    key, target = validate_api_credentials(api_key, url, "SUPOVER_DEAD_STORES_URL")
    headers = build_api_headers(api_key_header, key, include_content_type=False)
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



def all_store_and_profile_ids(
    stores: list[dict[str, Any]],
) -> list[tuple[int, str, str, str]]:
    """Return all ``(store_id, shop_code, region, profile_id)`` tuples from eligible stores."""
    results: list[tuple[int, str, str, str]] = []
    for store in stores:
        profile_hma = store.get("profile_hma")
        if not isinstance(profile_hma, dict):
            continue
        pid = profile_hma.get("profile_id")
        if not (isinstance(pid, str) and pid.strip()):
            continue
        sid = store.get("store_id")
        if sid is None:
            continue
        shop_code = store.get("shop_code")
        if not (isinstance(shop_code, str) and shop_code.strip()):
            continue
        region = store.get("region")
        region = region.strip().lower() if isinstance(region, str) and region.strip() else "us"
        results.append((int(sid), shop_code.strip(), region, pid.strip()))
    return results


def _unwrap_envelope(body: Any) -> dict[str, Any]:
    """Return the paginated envelope, tolerating list-of-one wrapping."""
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
