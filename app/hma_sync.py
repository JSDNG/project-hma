"""Pure HideMyAcc helpers used by the FastAPI service.

No FastAPI imports here; this module is independently usable.

Profiles API reference:
https://eng-hidemyacc.gitbook.io/hidemyacc-docs-vietnamese/hidemyacc-3.0-tinh-nang/hidemyacc-3.0-api/profile/danh-sach-profile
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

def _coerce_port(port_val: Any, profile_id: str, min_port: int, max_port: int) -> str:
    """Return a valid TCP port as a string, or '' for missing/invalid input."""
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
    if not (min_port <= port <= max_port):
        logging.warning(
            "Profile %s: proxy.port %d outside %d-%d; sending empty port",
            profile_id,
            port,
            min_port,
            max_port,
        )
        return ""
    return str(port)



def _proxy_dict(profile: dict[str, Any]) -> dict[str, Any]:
    p = profile.get("proxy")
    return p if isinstance(p, dict) else {}


def profile_to_sync_row(
    profile: dict[str, Any], min_port: int, max_port: int,
) -> dict[str, str]:
    """Map a HideMyAcc GET /profiles item to a flat row of string fields.

    Uses proxy.host, proxy.port, proxy.username, proxy.password when present;
    falls back to autoProxy* fields for other modes / older payloads.
    """
    proxy = _proxy_dict(profile)
    profile_id = str(profile.get("id", ""))
    port_str = _coerce_port(proxy.get("port"), profile_id, min_port, max_port)

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
    session: requests.Session, base_url: str, timeout: int, profiles_path: str,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + profiles_path
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


def fetch_profiles_response(
    session: requests.Session, base_url: str, timeout: int, profiles_path: str,
) -> Any:
    """Return the full HMA ``GET /profiles`` JSON body, untouched.

    Used by the scheduled Supover sync, which forwards whatever HMA returned
    verbatim. No shape validation, no data extraction — the caller is
    responsible for handling whatever HMA sent back.
    """
    url = base_url.rstrip("/") + profiles_path
    logging.info("GET %s", url)
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def delete_profile(
    session: requests.Session,
    base_url: str,
    profile_id: str,
    timeout: int,
    profiles_path: str,
) -> requests.Response:
    """DELETE /profiles/{profile_id} against the local HideMyAcc API."""
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id must be a non-empty string")
    url = base_url.rstrip("/") + profiles_path + "/" + pid
    logging.info("DELETE %s", url)
    return session.delete(url, timeout=timeout)


def _profile_action_url(base_url: str, action: str, profile_id: str, profiles_path: str) -> str:
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id must be a non-empty string")
    return f"{base_url.rstrip('/')}{profiles_path}/{action}/{pid}"


def start_profile(
    session: requests.Session,
    base_url: str,
    profile_id: str,
    timeout: int,
    profiles_path: str,
) -> requests.Response:
    """POST /profiles/start/{profile_id} against the local HideMyAcc API."""
    url = _profile_action_url(base_url, "start", profile_id, profiles_path)
    logging.info("POST %s", url)
    return session.post(url, timeout=timeout)


def stop_profile(
    session: requests.Session,
    base_url: str,
    profile_id: str,
    timeout: int,
    profiles_path: str,
) -> requests.Response:
    """POST /profiles/stop/{profile_id} against the local HideMyAcc API."""
    url = _profile_action_url(base_url, "stop", profile_id, profiles_path)
    logging.info("POST %s", url)
    return session.post(url, timeout=timeout)


@dataclass(frozen=True)
class StartResult:
    """Parsed outcome of an HMA /profiles/start/{id} call."""

    ok: bool
    ws_url: str | None
    port: int | None
    user_agent: str | None
    major_version: int | None
    error: str | None


def interpret_start_response(resp: requests.Response, start_success_code: int) -> StartResult:
    """Validate an HMA /profiles/start response and extract the wsUrl.

    Success requires HTTP 2xx, body.code == 1, body.data.success is True,
    and body.data.wsUrl is a non-empty string. Anything else yields ok=False
    with a human-readable ``error`` describing the mismatch.
    """
    if not (200 <= resp.status_code < 300):
        snippet = (resp.text or "")[:500]
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error=f"HMA returned HTTP {resp.status_code}: {snippet}",
        )

    body = parse_hma_body(resp)
    if body is None:
        snippet = (resp.text or "")[:500]
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error=f"HMA returned non-JSON body: {snippet}",
        )

    code = body.get("code")
    if code != start_success_code:
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error=f"HMA body code={code!r}, expected {start_success_code}",
        )

    data = body.get("data")
    if not isinstance(data, dict):
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error=f"HMA body.data is not an object: {type(data).__name__}",
        )

    if data.get("success") is not True:
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error=f"HMA body.data.success={data.get('success')!r}, expected True",
        )

    ws_url = data.get("wsUrl")
    if not isinstance(ws_url, str) or not ws_url.strip():
        return StartResult(
            ok=False,
            ws_url=None,
            port=None,
            user_agent=None,
            major_version=None,
            error="HMA body.data.wsUrl is missing or empty",
        )

    port_val = data.get("port")
    port = int(port_val) if isinstance(port_val, int) else None

    major_val = data.get("majorVersion")
    major_version = int(major_val) if isinstance(major_val, int) else None

    user_agent_val = data.get("userAgent")
    user_agent = user_agent_val if isinstance(user_agent_val, str) else None

    return StartResult(
        ok=True,
        ws_url=ws_url,
        port=port,
        user_agent=user_agent,
        major_version=major_version,
        error=None,
    )


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
