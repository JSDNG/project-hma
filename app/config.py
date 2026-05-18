"""Runtime configuration loaded from environment variables (and .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    hma_local_api_base: str = "http://127.0.0.1:2268"
    hma_profile_sync_api_key: str = ""
    hma_http_timeout: int = 30
    hma_log_level: str = "INFO"

    # Outbound sync to the Supover profile-hma endpoint, used by the
    # scheduled job in scripts/sync_to_supover.py. The runner script reads
    # these directly — the FastAPI service itself does not touch them.
    supover_sync_url: str = "https://ai.supover.com/api/profile-hma/sync"
    supover_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
