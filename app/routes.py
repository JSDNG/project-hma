"""HTTP endpoints for the FastAPI service."""

from __future__ import annotations

from typing import Annotated

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from .config import Settings, get_settings
from .hma_sync import (
    delete_profile,
    fetch_profiles,
    mask_secrets,
    parse_hma_body,
    post_sync,
    profile_to_sync_row,
    resolve_sync_post_url,
)
from .schemas import (
    BatchDeleteFailure,
    BatchDeleteRequest,
    BatchDeleteResponse,
    ConfigView,
    DeleteResponse,
    HealthResponse,
    ProfileRow,
    ProfilesResponse,
    SyncSummary,
)

HMA_DELETE_SUCCESS_CODE = 1
HMA_TEAM_PLAN_REQUIRED_DETAIL = (
    "HMA local API requires a Team plan subscription for this endpoint "
    "(HTTP 402, body code=0)."
)


def _interpret_hma_delete(
    resp: requests.Response,
) -> tuple[bool, int | None, str | None]:
    """Return (ok, code, error_detail) for an HMA DELETE response.

    - ok=True iff body.code == 1 (per HMA docs).
    - error_detail is a route-friendly message for the failure case.
    """
    body = parse_hma_body(resp)
    code = body.get("code") if body else None

    if code == HMA_DELETE_SUCCESS_CODE:
        return True, code, None

    if resp.status_code == 402 and code == 0:
        return False, code, HMA_TEAM_PLAN_REQUIRED_DETAIL

    snippet = (resp.text or "")[:500]
    return False, code, (
        f"HMA local API signaled failure (HTTP {resp.status_code}, "
        f"code={code}): {snippet}"
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


@router.delete(
    "/profiles/{profile_id}",
    response_model=DeleteResponse,
    tags=["profiles"],
    responses={
        402: {"description": "HMA Team plan required for this endpoint."},
        502: {"description": "Local HMA API unreachable or signaled failure."},
    },
)
def delete_one_profile(
    profile_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DeleteResponse:
    session = requests.Session()
    try:
        resp = delete_profile(
            session,
            settings.hma_local_api_base,
            profile_id,
            settings.hma_http_timeout,
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502, detail=f"HMA local API error: {e}"
        ) from e

    ok, code, detail = _interpret_hma_delete(resp)
    if ok:
        return DeleteResponse(
            profile_id=profile_id,
            deleted=True,
            upstream_status=resp.status_code,
        )

    status = 402 if (resp.status_code == 402 and code == 0) else 502
    raise HTTPException(status_code=status, detail=detail)


@router.delete(
    "/profiles",
    response_model=BatchDeleteResponse,
    tags=["profiles"],
)
def delete_many_profiles(
    body: BatchDeleteRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> BatchDeleteResponse:
    # Preserve order; drop duplicates so we don't 404 on the second pass of the same id.
    unique_ids = list(dict.fromkeys(pid for pid in body.profile_ids if pid.strip()))

    session = requests.Session()
    deleted_ids: list[str] = []
    failures: list[BatchDeleteFailure] = []

    for pid in unique_ids:
        try:
            resp = delete_profile(
                session,
                settings.hma_local_api_base,
                pid,
                settings.hma_http_timeout,
            )
        except requests.RequestException as e:
            failures.append(
                BatchDeleteFailure(
                    profile_id=pid, upstream_status=None, error=str(e)
                )
            )
            continue

        ok, _, detail = _interpret_hma_delete(resp)
        if ok:
            deleted_ids.append(pid)
        else:
            failures.append(
                BatchDeleteFailure(
                    profile_id=pid,
                    upstream_status=resp.status_code,
                    error=detail or f"HTTP {resp.status_code}",
                )
            )

    return BatchDeleteResponse(
        requested=len(unique_ids),
        deleted=len(deleted_ids),
        failed=len(failures),
        deleted_ids=deleted_ids,
        failures=failures,
    )
