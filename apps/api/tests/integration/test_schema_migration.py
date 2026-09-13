"""Revision `0003_automations_v2` must be idempotent.

Alembic is not the only thing that creates tables on this project: `app.main` runs
`Base.metadata.create_all` on every startup, so by the time anyone runs
`alembic upgrade head` the four builder tables normally already exist. An unguarded
`create_table` would fail there with `DuplicateTableError`, which would strand anyone
trying to adopt migrations on a database the app had already bootstrapped.

These tests run the revision's real `upgrade()` — loaded through Alembic's own script
directory, so there is no second copy of the DDL to drift — against the test database,
whose schema was built by `create_all`. The second call proves re-running is safe too.
"""

from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

import app as app_package

BUILDER_TABLES = ("automations", "automation_versions", "runs", "run_steps")
BUILDER_INDEXES = (
    "automations_updated_idx",
    "automation_versions_automation_idx",
    "runs_automation_created_idx",
    "run_steps_run_idx",
)


def _revision_module():
    """The `0003_automations_v2` module, as Alembic itself would load it."""
    api_root = pathlib.Path(app_package.__file__).resolve().parent.parent
    config = Config(str(api_root / "alembic.ini"))
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(config).get_revision("0003_automations_v2").module


def _run_upgrade(conn: sa.Connection) -> None:
    """Invoke the revision's `upgrade()` with the `alembic.op` proxy bound to `conn`."""
    module = _revision_module()
    context = MigrationContext.configure(conn)
    with Operations.context(context):
        module.upgrade()


def _snapshot(conn: sa.Connection) -> dict:
    inspector = inspect(conn)
    return {
        table: (
            {c["name"] for c in inspector.get_columns(table)},
            {i["name"] for i in inspector.get_indexes(table)},
        )
        for table in BUILDER_TABLES
    }


async def test_upgrade_is_a_noop_on_a_create_all_database(engine) -> None:
    """The exact case that used to raise DuplicateTableError."""
    async with engine.begin() as conn:
        before = await conn.run_sync(_snapshot)
        await conn.run_sync(_run_upgrade)
        after = await conn.run_sync(_snapshot)
    assert after == before


async def test_upgrade_twice_in_a_row_is_safe(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)
        first = await conn.run_sync(_snapshot)
        await conn.run_sync(_run_upgrade)
        assert await conn.run_sync(_snapshot) == first


async def test_upgrade_creates_everything_from_nothing(engine) -> None:
    """And it still builds the schema on a database that has none of it."""
    async with engine.begin() as conn:
        for table in reversed(BUILDER_TABLES):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        assert not any(
            await conn.run_sync(lambda c: [inspect(c).has_table(t) for t in BUILDER_TABLES])
        )

        await conn.run_sync(_run_upgrade)

        inspector_indexes = await conn.run_sync(
            lambda c: {i["name"] for t in BUILDER_TABLES for i in inspect(c).get_indexes(t)}
        )
        assert set(BUILDER_INDEXES) <= inspector_indexes
        columns = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("automations")}
        )
        assert {"valid", "enabled", "document", "current_version_id"} <= columns

    # Put the schema back the way the session bootstrap left it for the other tests.
    from app.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_the_guarded_columns_are_added_to_a_table_that_predates_them(engine) -> None:
    """`settings.timezone` / `automations.valid` land on tables `create_all` already made."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE settings DROP COLUMN IF EXISTS timezone"))
        await conn.execute(text("ALTER TABLE automations DROP COLUMN IF EXISTS valid"))

        await conn.run_sync(_run_upgrade)

        for table, column in (("settings", "timezone"), ("automations", "valid")):
            names = await conn.run_sync(
                lambda c, t=table: {col["name"] for col in inspect(c).get_columns(t)}
            )
            assert column in names
