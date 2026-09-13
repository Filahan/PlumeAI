"""DB-backed fixtures for the integration suite.

These tests talk to a real Postgres — the document language is pure and unit-testable,
but versioning, cascades, the 409 on a run already in flight and the JSONB round trip
are exactly the things a fake session would get wrong.

Isolation strategy: one throwaway database (`plumeai_test`, derived from `DATABASE_URL`)
created on demand next to the dev one, schema rebuilt from the models once per session,
and every table truncated between tests. Truncate rather than a per-test transaction
rollback because the API commits inside request handlers (`POST /runs` does, so a
background executor could see the row) — a wrapping transaction would be closed out from
under the test.

The whole `public` schema is dropped and recreated rather than `create_all`-ed onto
whatever is there: `create_all` skips tables that already exist, so a column added to a
model after a previous run (`automations.valid`) would never appear and the suite would
fail against a database it had itself left stale. Dropping the schema rather than calling
`Base.metadata.drop_all` also clears tables whose *model* has since been deleted
(`conversations`/`messages`) — `drop_all` only knows about the models that still exist, so
it would leave those behind forever and a test asserting they are absent would pass in CI
and fail on a developer machine.

Two pieces of the app are deliberately inert here. The executor is replaced by a
recorder (see `no_background_runs`) so `POST /runs` leaves a `queued` run with `pending`
steps for the test to assert on instead of racing a real execution; and the scheduler is
never started, because `ASGITransport` does not run the app's lifespan — its `sync_job`
sees no active scheduler and no-ops.

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
    """Rebuild every table from the models, discarding whatever a previous run left."""
    assert TEST_DB_NAME.endswith("_test"), (
        f"refusing to drop the schema of {TEST_DB_NAME!r} — the throwaway database name "
        "must end in `_test` or this could tear down someone's real data"
    )
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            # Safe because this database exists only for the suite (see the module
            # docstring) — nothing here is ever anyone's data.
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
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


@pytest.fixture(autouse=True)
def no_background_runs(monkeypatch) -> list[str]:
    """Stop `POST /runs` from actually executing the run it just queued.

    Task 4b's executor is real: `start_run_in_background` spawns an asyncio task that
    drives the run to completion against its own session. That makes every assertion
    about a freshly created run ("status is queued", "steps are pending") a race, and
    leaves background tasks holding an engine this fixture's teardown is about to
    dispose. These tests are about the persistence and API layer, so the hand-off point
    is stubbed and the recorded ids are returned for tests that want to assert on it.
    `app.services.executor` itself is covered by `test_executor.py`.
    """
    started: list[str] = []

    def record(run_id: str) -> None:
        started.append(run_id)

    monkeypatch.setattr(
        "app.services.executor.start_run_in_background", record, raising=True
    )
    # The router imported the module, not the name, so patching the module attribute is
    # enough — but assert that stays true rather than silently stubbing nothing.
    import app.routers.automations as router_module

    assert router_module.executor.start_run_in_background is record
    return started


# --- document builders ---------------------------------------------------------------------
#
# Exposed as fixtures rather than importable helpers: the integration suite must not be
# imported from by name, or it starts competing with `tests/conftest.py` for the
# top-level `conftest` module the pure suite imports.


@pytest.fixture
def ai_step():
    """Build a minimal valid `ai` step — needs no catalog entry, so it validates cleanly."""

    def build(
        step_id: str, name: str = "Draft a reply", instructions: str = "Say hi"
    ) -> dict:
        return {
            "id": step_id,
            "name": name,
            "type": "ai",
            "settings": {
                "instructions": instructions,
                "tools": [],
                "output": {"mode": "text"},
            },
        }

    return build


@pytest.fixture
def make_document():
    """Build a manual-trigger document around the given steps."""

    def build(name: str = "Test automation", steps: list[dict] | None = None) -> dict:
        return {
            "name": name,
            "description": "",
            "model": {"provider": "openai", "model": "gpt-4o-mini"},
            "trigger": {"type": "manual"},
            "steps": steps if steps is not None else [],
        }

    return build
