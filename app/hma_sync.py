"""Pure HideMyAcc helpers used by the FastAPI service.

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

import requests

DEFAULT_HMA_BASE = "http://127.0.0.1:2268"
DEFAULT_PROFILES_PATH = "/profiles"
DEFAULT_TIMEOUT = 30

MIN_TCP_PORT = 1
MAX_TCP_PORT = 65535


def _coerce_port(port_val: Any, profile_id: str) -> str:
    """Return a valid TCP port as a string, or '' for missing/invalid input.

    Why: Supover's `profile_hma.port` is an INT column in MySQL strict mode,
    so a single out-of-range value (e.g. a corrupted upstream record with a
    timestamp or IP digits in `proxy.port`) aborts the entire batch insert
    with SQLSTATE 22003. Filter here so one bad profile can't sink the sync.
    """
    if port_val in (None, "", 0):
        return ""
    try:
        port = int(port_val)
    except (TypeError, ValueError):
        logging.warning(
            "Profile %s: non-numeric proxy.port %r; sending empty port",
            profile_id,
            port_val,
        )
        return ""
    if not (MIN_TCP_PORT <= port <= MAX_TCP_PORT):
        logging.warning(
            "Profile %s: proxy.port %d outside %d-%d; sending empty port",
            profile_id,
            port,
            MIN_TCP_PORT,
            MAX_TCP_PORT,
        )
        return ""
    return str(port)


def setup_logging(log_file: Path | None = None, level: str | int = "INFO") -> None:
    """Configure root logging for the API service."""
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
    """Map a HideMyAcc GET /profiles item to a flat row of string fields.

    Uses proxy.host, proxy.port, proxy.username, proxy.password when present;
    falls back to autoProxy* fields for other modes / older payloads.
    """
    proxy = _proxy_dict(profile)
    profile_id = str(profile.get("id", ""))
    port_str = _coerce_port(proxy.get("port"), profile_id)

    host = (proxy.get("host") or proxy.get("autoProxyServer") or "").strip()
    username = proxy.get("username") or proxy.get("autoProxyUsername") or ""
    password = proxy.get("password") or proxy.get("autoProxyPassword") or ""

    return {
        "profile_id": profile_id,
        "profile_name": str(profile.get("name", "")),
        "proxy": host,
        "port": port_str,
        "username": str(username),
        "password": str(password),
    }


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
