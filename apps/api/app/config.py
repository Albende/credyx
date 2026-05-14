"""Runtime configuration. Reads from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server.
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log_level: str = "INFO"

    # Infra.
    database_url: str = "postgresql+asyncpg://creditlens:creditlens@localhost:5432/creditlens"
    redis_url: str = "redis://localhost:6379/0"

    # Rate limit (per IP).
    rate_limit_per_minute: int = 60

    # LLM.
    kie_ai_api_key: str | None = None
    kie_ai_model: str = "gemini-2.0-flash"

    # Cache TTLs (seconds).
    company_cache_ttl_seconds: int = 7 * 24 * 3600
    financials_cache_ttl_seconds: int = 30 * 24 * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
