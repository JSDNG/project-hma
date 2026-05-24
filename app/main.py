"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .helpers.logging import setup_logging
from .routes import router

tags_metadata = [
    {"name": "system", "description": "Liveness and effective-configuration endpoints."},
    {"name": "profiles", "description": "Inspect and delete HideMyAcc profiles."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.hma_log_level)
    yield


app = FastAPI(
    title="HMA Profile API",
    version="1.0.0",
    summary="Stateless HTTP wrapper around the local HideMyAcc profile API.",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)
app.include_router(router)
