"""FastAPI application entrypoint.

Phase 0 ship: healthcheck + structured logging + Problem Details error handlers. Other
routers (auth, settings, chat, automations, tools, usage) are registered in later phases.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI

from app.config import get_settings
from app.errors import register_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestLoggingMiddleware
from app.routers import auth as auth_router
from app.routers import automations as automations_router
from app.routers import chat as chat_router
from app.routers import settings as settings_router
from app.routers import tools as tools_router
from app.routers import usage as usage_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler — runs startup before the first request and cleanup on shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("app.lifespan")
    log.info("startup", env=settings.app_env)
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
