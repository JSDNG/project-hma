"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .hma_sync import setup_logging
from .routes import router

tags_metadata = [
    {"name": "system", "description": "Liveness and effective-configuration endpoints."},
    {"name": "profiles", "description": "Inspect mapped profile rows."},
    {"name": "sync", "description": "Run the fetch-and-forward sync pipeline."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.hma_log_level)
    yield


app = FastAPI(
    title="HMA Profile Sync API",
    version="1.0.0",
    summary="Stateless HTTP wrapper over the HideMyAcc profile sync pipeline.",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)
app.include_router(router)
