"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings

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
        tiktok_seller_login_url="https://seller-{region}.tiktok.com/account/login",
        tiktok_seller_bills_url="https://seller-us.tiktok.com/finance/bills",
        tiktok_shop_info_api_url="https://seller-{region}.tiktok.com/api/v1/seller/common/get",
        tiktok_element_timeout=15000,
        tiktok_login_wait_seconds=15,
        tiktok_step_delay=5,
        tiktok_dwell_seconds=300,
        xpath_pending_balance="//test/xpath",
        xpath_on_hold="//test/xpath",
        xpath_bank_account="//test/xpath",
        telegram_bot_token="test-bot-token",
        telegram_chat_id="test-chat-id",
    )
