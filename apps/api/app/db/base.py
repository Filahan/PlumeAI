"""Async SQLAlchemy engine + session factory.

Single engine for the process lifetime. Each request gets its own AsyncSession via the
`get_session` dependency; background work (the executor, the scheduler) uses
`session_scope()` instead, which owns its own session and commit boundary.

The engine is created **lazily** on first use rather than at import time so that
importing `app.main` never opens a connection pool against whatever `DATABASE_URL`
happens to be set — the integration tests rebind the engine to a throwaway test
database via `configure_engine()` before the first session is ever requested. In
production nothing changes: the first request (or the startup lifespan) builds the same
engine with the same options it always had.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        # Sized for the executor: a run holds one connection for its whole duration (the
        # tool registry and the agent loop share the run's session), and up to
        # `executor.MAX_CONCURRENT_RUNS` runs execute at once, so the pool has to cover
        # those plus the requests being served alongside them.
        pool_size=10,
        max_overflow=10,
    )


def get_engine() -> AsyncEngine:
    """The process-wide engine. Used by Alembic env.py and by the session factory."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The process-wide session factory, bound to `get_engine()`."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


def configure_engine(engine: AsyncEngine | None) -> None:
    """Rebind the process engine (and its session factory).

    Test-only hook: pass an engine pointed at the throwaway test database, or `None` to
    reset back to lazy construction from `DATABASE_URL`.
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = (
        None
        if engine is None
        else async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a session, commits on success, rolls back on error."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for work that happens outside a request (background runs, startup tasks).

    Same commit-on-success / rollback-on-error contract as `get_session`, but usable as
    `async with session_scope() as session:` from anywhere.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
