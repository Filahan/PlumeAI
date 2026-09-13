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

    # Crypto
    encryption_key_b64: str = Field(..., alias="ENCRYPTION_KEY")

    # Public frontend URL. OAuth callback URIs are anchored on this so the user always
    # comes back through the nginx proxy, regardless of how `gmail_oauth_start` was
    # reached internally.
    frontend_url: str = Field(default="http://localhost:3001", alias="FRONTEND_URL")

    # App
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # MCP: whether `stdio` servers may be registered. A stdio MCP server is a command the
    # API container runs as a subprocess, so with no built-in login (see `app/auth.py`)
    # anyone who can reach the API can execute arbitrary commands inside the container.
    # `http` MCP servers are unaffected (they are just an outbound request, SSRF-guarded).
    #
    # Kept as a string rather than `bool | None` on purpose: `docker-compose.yml` passes
    # it through as `${MCP_ALLOW_STDIO:-}`, and an empty value has to mean "not set"
    # (follow `APP_ENV`) rather than fail the whole process at startup.
    mcp_allow_stdio_override: str | None = Field(default=None, alias="MCP_ALLOW_STDIO")

    @property
    def mcp_allow_stdio(self) -> bool:
        """Unset → on in development, off everywhere else. Anything unrecognized → off."""
        raw = (self.mcp_allow_stdio_override or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if not raw:
            return self.app_env.strip().lower() in ("dev", "development", "local", "test")
        # An explicit "false" — or a typo, which fails closed rather than open.
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Single instance for the lifetime of the process."""
    return Settings()  # type: ignore[call-arg]
