"""Pydantic models for request/response serialization."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class ConfigView(BaseModel):
    hma_local_api_base: str
    sync_post_url: str
    hma_api_key: str
    hma_http_timeout: int
    hma_log_level: str


class ProfileRow(BaseModel):
    profile_id: str
    profile_name: str
    proxy: str
    port: str
    username: str
    password: str
    user_agent: str


class ProfilesResponse(BaseModel):
    count: int
    rows: list[ProfileRow]


class SyncSummary(BaseModel):
    rows_fetched: int
    rows_forwarded: int
    dry_run: bool
    sync_url: str
    downstream_status: int | None = Field(default=None)
    downstream_body: str | None = Field(default=None)
