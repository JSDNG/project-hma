"""Runtime configuration loaded from environment variables (and .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    hma_local_api_base: str = ""
    hma_profiles_path: str = ""
    hma_http_timeout: int = 30
    hma_log_level: str = "INFO"
    hma_start_success_code: int = 1
    hma_delete_success_code: int = 1
    hma_min_tcp_port: int = 1
    hma_max_tcp_port: int = 65535

    supover_api_key: str = ""
    supover_api_key_header: str = ""
    supover_sync_url: str = ""
    supover_dead_stores_url: str = ""
    supover_stores_sync_url: str = ""

    tiktok_seller_login_url: str = ""
    tiktok_seller_bills_url: str = ""
    tiktok_shop_info_api_url: str = ""
    tiktok_element_timeout: int = 15000
    tiktok_step_delay: int = 5
    tiktok_dwell_seconds: int = 300
    xpath_pending_balance: str = ""
    xpath_on_hold: str = ""
    xpath_bank_account: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
