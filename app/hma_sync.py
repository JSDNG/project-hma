"""Pure HideMyAcc sync logic, shared by the CLI script and the FastAPI service.

No FastAPI imports here; this module is independently usable.

Profiles API reference:
https://eng-hidemyacc.gitbook.io/hidemyacc-docs-vietnamese/hidemyacc-3.0-tinh-nang/hidemyacc-3.0-api/profile/danh-sach-profile
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_HMA_BASE = "http://127.0.0.1:2268"
DEFAULT_PROFILES_PATH = "/profiles"
DEFAULT_TIMEOUT = 30
DEFAULT_HMA_PROFILES_SYNC_URL = "https://n8n.supover.com/webhook"
SYNC_POST_SUFFIX = "/api/hma-profiles/sync"


def setup_logging(log_file: Path | None = None, level: str | int = "INFO") -> None:
    """Configure root logging for both the CLI and the API."""
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8", mode="a"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _proxy_dict(profile: dict[str, Any]) -> dict[str, Any]:
    p = profile.get("proxy")
    return p if isinstance(p, dict) else {}


def profile_to_sync_row(profile: dict[str, Any]) -> dict[str, str]:
    """Map a HideMyAcc GET /profiles item to one POST body row (all string fields).

    Uses proxy.host, proxy.port, proxy.username, proxy.password when present;
    falls back to autoProxy* fields for other modes / older payloads.
    """
    proxy = _proxy_dict(profile)
    port_val = proxy.get("port")
    port_str = "" if port_val in (None, "", 0) else str(port_val)

    host = (proxy.get("host") or proxy.get("autoProxyServer") or "").strip()
    username = proxy.get("username") or proxy.get("autoProxyUsername") or ""
    password = proxy.get("password") or proxy.get("autoProxyPassword") or ""

    user_agent = (
        profile.get("userAgent")
        or profile.get("user_agent")
        or profile.get("userAgentOverride")
        or ""
    )
    if not isinstance(user_agent, str):
        user_agent = str(user_agent)

    return {
        "profile_id": str(profile.get("id", "")),
        "profile_name": str(profile.get("name", "")),
        "proxy": host,
        "port": port_str,
        "username": str(username),
        "password": str(password),
        "user_agent": user_agent,
    }


def mask_secrets(row: dict[str, str]) -> dict[str, str]:
    """Return a copy of a row with the password redacted (empty strings preserved)."""
    out = dict(row)
    if out.get("password"):
        out["password"] = "***"
    return out


def fetch_profiles(
    session: requests.Session, base_url: str, timeout: int
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + DEFAULT_PROFILES_PATH
    logging.info("GET %s", url)
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    code = body.get("code")
    data = body.get("data")
    logging.info("HMA response code field: %s", code)
    if not isinstance(data, list):
        logging.error("Unexpected shape: data is not a list: %s", type(data).__name__)
        raise ValueError("Invalid HMA /profiles response: missing or invalid 'data' array")

    logging.info("Profile count: %d", len(data))
    if data:
        sample = data[0]
        logging.info("Keys on first profile item: %s", sorted(sample.keys()))
        logging.debug(
            "Sample profile (JSON): %s",
            json.dumps(sample, ensure_ascii=False, indent=2),
        )
        pr = _proxy_dict(sample)
        if pr:
            logging.info("Keys on first item's proxy: %s", sorted(pr.keys()))
    return data


def delete_profile(
    session: requests.Session,
    base_url: str,
    profile_id: str,
    timeout: int,
) -> requests.Response:
    """DELETE /profiles/{profile_id} against the local HideMyAcc API."""
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id must be a non-empty string")
    url = base_url.rstrip("/") + DEFAULT_PROFILES_PATH + "/" + pid
    logging.info("DELETE %s", url)
    return session.delete(url, timeout=timeout)


def parse_hma_body(resp: requests.Response) -> dict[str, Any] | None:
    """Return the response body as a dict if it parsed as JSON, else None.

    The HMA local API uses a body-level ``code`` field whose semantics are
    endpoint-specific (e.g. ``DELETE /profiles/{id}`` uses ``code == 1`` for
    success and ``code == 0`` with HTTP 402 for "API supported from Team
    plan"). Callers must interpret ``code`` themselves.
    """
    try:
        parsed = resp.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def post_sync(
    session: requests.Session,
    sync_url: str,
    api_key: str,
    rows: list[dict[str, str]],
    timeout: int,
) -> requests.Response:
    payload = {"data": rows}
    logging.info("POST %s (rows: %d)", sync_url, len(rows))
    logging.debug(
        "Payload (passwords masked): %s",
        json.dumps({"data": [mask_secrets(r) for r in rows]}, ensure_ascii=False)[:8000],
    )
    return session.post(
        sync_url,
        headers={
            "X-Api-Key": api_key.strip(),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )


def resolve_sync_post_url(url: str) -> str:
    """Resolve the full POST URL from a webhook base or origin.

    - Already ends with .../api/hma-profiles/sync → unchanged.
    - Origin only (no path) → .../webhook + SYNC_POST_SUFFIX.
    - Otherwise (e.g. .../webhook) → base + SYNC_POST_SUFFIX.
    """
    u = url.strip().rstrip("/")
    if not u:
        return u
    if u.endswith(SYNC_POST_SUFFIX):
        return u
    parsed = urlparse(u)
    path = (parsed.path or "").strip("/")
    if not path:
        return u + "/webhook" + SYNC_POST_SUFFIX
    return u + SYNC_POST_SUFFIX
