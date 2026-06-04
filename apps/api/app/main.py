"""FastAPI application entrypoint — registers all routers, healthcheck, and the lifespan
that applies idempotent runtime migrations on startup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_engine
from app.errors import register_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestLoggingMiddleware
from app.routers import auth as auth_router
from app.routers import automations as automations_router
from app.routers import chat as chat_router
from app.routers import conversations as conversations_router
from app.routers import settings as settings_router
from app.routers import tools as tools_router
from app.routers import usage as usage_router


async def _apply_runtime_migrations() -> None:
    """Idempotent ALTER TABLE statements applied on startup.

    Cheaper than running Alembic from the container entrypoint and keeps schema
    drift in sync for self-hosted users who don't run migrations manually.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
                "tool_credentials JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler — runs startup before the first request and cleanup on shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("app.lifespan")
    log.info("startup", env=settings.app_env)
    try:
        await _apply_runtime_migrations()
    except Exception:  # noqa: BLE001
        log.warning("runtime_migrations_failed", exc_info=True)
    try:
        yield
    finally:
        log.info("shutdown")


app = FastAPI(
    title="PlumeAI API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
register_handlers(app)

# --- Healthcheck router ---------------------------------------------------------------------

health = APIRouter(tags=["health"])


@health.get("/health")
async def healthcheck() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is up. Doesn't touch the DB."""
    return {"status": "ok"}


app.include_router(health)
app.include_router(auth_router.router)
app.include_router(settings_router.router)
app.include_router(chat_router.router)
app.include_router(tools_router.router)
app.include_router(automations_router.router)
app.include_router(usage_router.router)
app.include_router(conversations_router.router)
