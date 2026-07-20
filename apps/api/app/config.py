"""Runtime configuration. Reads from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server.
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3005",
        "http://127.0.0.1:3005",
    ]
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

    # Auth / JWT.
    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    password_pepper: str = ""

    # Stripe.
    stripe_api_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_default_currency: str = "usd"
    billing_success_url: str = "http://localhost:3005/app/account/subscription?subscribed=true"
    billing_cancel_url: str = "http://localhost:3005/pricing?canceled=true"

    # Email (MailHog defaults for local dev — port 1025, no TLS, no auth).
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@creditlens.local"
    public_app_url: str = "http://localhost:3005"

    # Admin bootstrap: first user with this email gets role=admin on register.
    bootstrap_admin_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
