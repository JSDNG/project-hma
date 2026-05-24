"""x-api-key authentication for incoming requests."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import Settings, get_settings

API_KEY_HEADER_NAME = "x-api-key"

_api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    provided: Annotated[str | None, Security(_api_key_header)],
) -> None:
    """Reject requests that don't carry the configured x-api-key header.

    Fail-closed: when the server has no SUPOVER_API_KEY configured,
    every request is rejected. Prevents a misconfigured deployment from
    quietly accepting unauthenticated traffic.
    """
    expected = settings.supover_api_key.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPOVER_API_KEY is not configured on the server",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing x-api-key",
        )
