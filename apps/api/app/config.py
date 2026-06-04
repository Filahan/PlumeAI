"""Environment configuration. Validated at startup so misconfigured deploys fail fast."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables (see .env.example for defaults)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres
    database_url: str = Field(..., alias="DATABASE_URL")

    # JWT + cookie session
    auth_secret: str = Field(..., alias="AUTH_SECRET")
    admin_password_hash: str = Field(..., alias="ADMIN_PASSWORD_HASH")
    session_cookie_name: str = "plumeai_session"
    session_lifetime_seconds: int = 30 * 24 * 60 * 60  # 30 days

    # Crypto
    encryption_key_b64: str = Field(..., alias="ENCRYPTION_KEY")

    # Public frontend URL. OAuth callback URIs are anchored on this so the user always
    # comes back through the nginx proxy (which sets the session cookie), regardless of
    # how `gmail_oauth_start` was reached internally.
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    # App
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Single instance for the lifetime of the process."""
    return Settings()  # type: ignore[call-arg]
