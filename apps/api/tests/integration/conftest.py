"""DB-backed fixtures for the integration suite.

These tests talk to a real Postgres — the document language is pure and unit-testable,
but versioning, cascades, the 409 on a run already in flight and the JSONB round trip
are exactly the things a fake session would get wrong.

Isolation strategy: one throwaway database (`plumeai_test`, derived from `DATABASE_URL`)
created on demand next to the dev one, schema built once per session with
`Base.metadata.create_all`, and every table truncated between tests. Truncate rather
than a per-test transaction rollback because the API commits inside request handlers
(`POST /runs` does, so a background executor could see the row) — a wrapping transaction
would be closed out from under the test.

Engines are built per test rather than shared: asyncpg connections are bound to the
event loop that created them, and `asyncio_mode = auto` gives each test its own loop.
The one-time bootstrap therefore runs in its own `asyncio.run`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import models  # noqa: F401 — registers every table on Base.metadata
from app.db.base import Base, configure_engine, get_session
from app.main import app

TEST_DB_NAME = "plumeai_test"


def _test_database_url() -> str:
    """`DATABASE_URL` with the database name swapped for the throwaway one."""
    parts = urlsplit(get_settings().database_url)
    return urlunsplit(parts._replace(path=f"/{TEST_DB_NAME}"))


def _admin_dsn() -> str:
    """A plain asyncpg DSN for the *original* database, used only to `CREATE DATABASE`."""
    parts = urlsplit(get_settings().database_url)
    scheme = parts.scheme.split("+", 1)[0]  # postgresql+asyncpg → postgresql
    return urlunsplit(parts._replace(scheme=scheme))


async def _ensure_database() -> None:
    import asyncpg

    conn = await asyncpg.connect(_admin_dsn())
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _create_schema() -> None:
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_database() -> None:
    """Create the test database and its schema once, in its own event loop."""

    async def run() -> None:
        await _ensure_database()
        await _create_schema()

    asyncio.run(run())


_TRUNCATE = "TRUNCATE TABLE {} RESTART IDENTITY CASCADE".format(
    ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
)


@pytest_asyncio.fixture
async def engine(_bootstrap_database: None) -> AsyncIterator:
    """A fresh engine on this test's event loop, with every table emptied first.

    Also rebinds the app's process engine, so code that opens its own session
    (`session_scope`, background work) hits the test database too.
    """
    eng = create_async_engine(_test_database_url(), poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text(_TRUNCATE))
    configure_engine(eng)
    try:
        yield eng
    finally:
        configure_engine(None)
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    """A session for the test body itself, committed at the end so assertions that go
    back through the API see what the test set up."""
    async with session_factory() as s:
        yield s
        await s.commit()


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    """An httpx client wired straight to the ASGI app (no network, no lifespan)."""

    async def _override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


# --- document helpers used across the integration tests ---------------------------------


def ai_step(step_id: str, name: str = "Draft a reply", instructions: str = "Say hi") -> dict:
    """A minimal valid `ai` step — needs no catalog entry, so it validates cleanly."""
    return {
        "id": step_id,
        "name": name,
        "type": "ai",
        "settings": {"instructions": instructions, "tools": [], "output": {"mode": "text"}},
    }


def document(name: str = "Test automation", steps: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "description": "",
        "model": {"provider": "openai", "model": "gpt-4o-mini"},
        "trigger": {"type": "manual"},
        "steps": steps if steps is not None else [],
    }
