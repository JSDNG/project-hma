"""Runtime configuration loaded from environment variables (and .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    hma_local_api_base: str = "http://127.0.0.1:2268"
    hma_profiles_sync_url: str = "https://n8n.supover.com/webhook"
    hma_api_key: str = ""
    hma_http_timeout: int = 30
    hma_log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
