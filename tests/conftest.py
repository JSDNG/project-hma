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
        hma_profiles_path="/profiles",
        hma_http_timeout=5,
        hma_log_level="INFO",
        hma_start_success_code=1,
        hma_delete_success_code=1,
        hma_min_tcp_port=1,
        hma_max_tcp_port=65535,
        supover_api_key=TEST_SYNC_API_KEY,
        supover_api_key_header="x-api-key",
        supover_sync_url="https://supover.test/api/hma/profiles/sync",
        supover_dead_stores_url="https://supover.test/api/hma/stores/dead-with-balance",
        supover_stores_sync_url="https://supover.test/api/hma/stores/sync",
        tiktok_seller_bills_url="https://seller-us.tiktok.com/finance/bills",
        tiktok_health_center_url="https://seller-us.tiktok.com/health-center",
        tiktok_account_deactivated_text="Account deactivated",
        tiktok_element_timeout=15000,
        tiktok_step_delay=5,
        tiktok_dwell_seconds=300,
        xpath_pending_balance="//test/xpath",
        xpath_on_hold="//test/xpath",
        xpath_bank_account="//test/xpath",
        xpath_account_status="//test/xpath",
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
