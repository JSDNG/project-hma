"""Pydantic models for request/response serialization."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class ConfigView(BaseModel):
    hma_local_api_base: str
    hma_http_timeout: int
    hma_log_level: str


class ProfileRow(BaseModel):
    profile_id: str
    profile_name: str
    proxy: str
    port: str
    username: str
    password: str


class ProfilesResponse(BaseModel):
    count: int
    data: list[ProfileRow]


class DeleteResponse(BaseModel):
    profile_id: str
    deleted: bool
    upstream_status: int


class BatchDeleteRequest(BaseModel):
    profile_ids: list[str] = Field(
        ...,
        min_length=1,
        description="One or more HideMyAcc profile IDs to delete.",
    )


class BatchDeleteFailure(BaseModel):
    profile_id: str
    upstream_status: int | None = Field(
        default=None,
        description="HTTP status returned by HMA for this ID, or null on network error.",
    )
    error: str


class BatchDeleteResponse(BaseModel):
    requested: int
    deleted: int
    failed: int
    deleted_ids: list[str]
    failures: list[BatchDeleteFailure]
