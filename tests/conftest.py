"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import API_KEY_HEADER_NAME
from app.config import Settings, get_settings
from app.main import app

TEST_SYNC_API_KEY = "test-sync-key"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        hma_local_api_base="http://hma.test",
        hma_profile_sync_api_key=TEST_SYNC_API_KEY,
        hma_http_timeout=5,
        hma_log_level="INFO",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, headers={API_KEY_HEADER_NAME: TEST_SYNC_API_KEY}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client(settings: Settings) -> Iterator[TestClient]:
    """TestClient with no default x-api-key header — for auth tests."""
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
