"""HTTP endpoints for the FastAPI service."""

from __future__ import annotations

from typing import Annotated

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from .config import Settings, get_settings
from .hma_sync import (
    fetch_profiles,
    mask_secrets,
    post_sync,
    profile_to_sync_row,
    resolve_sync_post_url,
)
from .schemas import (
    ConfigView,
    HealthResponse,
    ProfileRow,
    ProfilesResponse,
    SyncSummary,
)

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["system"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/config", response_model=ConfigView, tags=["system"])
def show_config(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConfigView:
    return ConfigView(
        hma_local_api_base=settings.hma_local_api_base,
        sync_post_url=resolve_sync_post_url(settings.hma_profiles_sync_url),
        hma_api_key="***" if settings.hma_api_key else "",
        hma_http_timeout=settings.hma_http_timeout,
        hma_log_level=settings.hma_log_level,
    )


def _fetch_rows(settings: Settings) -> list[dict[str, str]]:
    session = requests.Session()
    try:
        profiles = fetch_profiles(
            session, settings.hma_local_api_base, settings.hma_http_timeout
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502, detail=f"HMA local API error: {e}"
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=502, detail=f"Invalid HMA response: {e}"
        ) from e
    return [profile_to_sync_row(p) for p in profiles]


@router.get("/profiles", response_model=ProfilesResponse, tags=["profiles"])
def list_profiles(
    settings: Annotated[Settings, Depends(get_settings)],
    reveal: bool = Query(
        False, description="If true, do not mask proxy passwords."
    ),
) -> ProfilesResponse:
    rows = _fetch_rows(settings)
    if not reveal:
        rows = [mask_secrets(r) for r in rows]
    return ProfilesResponse(count=len(rows), rows=[ProfileRow(**r) for r in rows])


@router.post("/sync", response_model=SyncSummary, tags=["sync"])
def trigger_sync(
    settings: Annotated[Settings, Depends(get_settings)],
    dry_run: bool = Query(
        False,
        description="If true, fetch + map but do not POST to the downstream webhook.",
    ),
) -> SyncSummary:
    if not dry_run and not settings.hma_api_key.strip():
        raise HTTPException(status_code=400, detail="HMA_API_KEY is not configured")

    rows = _fetch_rows(settings)
    sync_url = resolve_sync_post_url(settings.hma_profiles_sync_url)

    if dry_run or not rows:
        return SyncSummary(
            rows_fetched=len(rows),
            rows_forwarded=0,
            dry_run=dry_run,
            sync_url=sync_url,
        )

    session = requests.Session()
    try:
        resp = post_sync(
            session, sync_url, settings.hma_api_key, rows, settings.hma_http_timeout
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502, detail=f"Sync webhook error: {e}"
        ) from e

    if not resp.ok:
        raise HTTPException(
            status_code=502,
            detail=f"Sync webhook responded HTTP {resp.status_code}: {resp.text[:500]}",
        )

    return SyncSummary(
        rows_fetched=len(rows),
        rows_forwarded=len(rows),
        dry_run=False,
        sync_url=sync_url,
        downstream_status=resp.status_code,
        downstream_body=resp.text[:4000],
    )
