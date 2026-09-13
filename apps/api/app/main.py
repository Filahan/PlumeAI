"""FastAPI application entrypoint — registers all routers, healthcheck, and the lifespan
that applies idempotent runtime migrations on startup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db import models  # noqa: F401 — registers the tables on Base.metadata
from app.db.base import Base, get_engine, session_scope
from app.errors import register_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestLoggingMiddleware
from app.routers import automations as automations_router
from app.routers import chat as chat_router
from app.routers import conversations as conversations_router
from app.routers import settings as settings_router
from app.routers import tools as tools_router
from app.routers import usage as usage_router
from app.services.legacy_migration import convert_legacy_tasks
from app.services.runs import mark_orphaned_runs_failed


async def _ensure_schema() -> None:
    """Create any missing tables on a fresh database.

    Alembic's baseline revision is intentionally empty and relies on this call (see
    alembic/versions/*_baseline.py), so a brand-new `docker compose up` gets a usable
    schema without running migrations by hand. Existing tables are left untouched.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _apply_runtime_migrations() -> None:
    """Idempotent schema changes applied on startup.

    Cheaper than running Alembic from the container entrypoint and keeps schema
    drift in sync for self-hosted users who don't run migrations manually. Every
    statement here has a counterpart in an Alembic revision (currently
    `0002_tool_credentials` and `0003_automations_v2`) and both paths are guarded the
    same way, so whichever runs first wins and the other is a no-op.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
                "tool_credentials JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
                "timezone TEXT NOT NULL DEFAULT 'UTC'"
            )
        )

        # Legacy tasks → automations, once. `tasks_legacy` existing is the marker that
        # the conversion already happened (by this path or by `alembic upgrade`).
        has_tasks = (
            await conn.execute(text("SELECT to_regclass('public.tasks')"))
        ).scalar()
        has_legacy = (
            await conn.execute(text("SELECT to_regclass('public.tasks_legacy')"))
        ).scalar()
        if has_tasks is not None and has_legacy is None:
            converted = await conn.run_sync(convert_legacy_tasks)
            await conn.execute(text("ALTER TABLE tasks RENAME TO tasks_legacy"))
            log = get_logger("app.lifespan")
            log.info("legacy_tasks_migrated", converted=converted)


async def _recover_interrupted_runs() -> None:
    """Fail any run left `queued`/`running` by the previous process.

    Runs only exist in the API process, so nothing is executing them after a restart;
    without this they would block new runs of the same automation forever (409).
    """
    async with session_scope() as session:
        await mark_orphaned_runs_failed(session)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler — runs startup before the first request and cleanup on shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("app.lifespan")
    log.info("startup", env=settings.app_env)
    try:
        await _ensure_schema()
        await _apply_runtime_migrations()
        await _recover_interrupted_runs()
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
app.include_router(settings_router.router)
app.include_router(chat_router.router)
app.include_router(tools_router.router)
app.include_router(automations_router.router)
app.include_router(usage_router.router)
app.include_router(conversations_router.router)
