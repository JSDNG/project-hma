"""Shared HTTP utilities for outbound API calls."""

from __future__ import annotations


def validate_api_credentials(api_key: str, url: str, url_env_name: str) -> tuple[str, str]:
    """Validate and strip API key and URL. Return (key, target).

    Raises ``ValueError`` if either is empty after stripping.
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("SUPOVER_API_KEY is not configured; refusing to call API")

    target = (url or "").strip()
    if not target:
        raise ValueError(f"{url_env_name} is empty; refusing to call API")

    return key, target


def build_api_headers(
    api_key_header: str, key: str, *, include_content_type: bool = True,
) -> dict[str, str]:
    """Build standard headers for Supover API calls."""
    headers: dict[str, str] = {
        api_key_header: key,
        "Accept": "application/json",
    }
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers
