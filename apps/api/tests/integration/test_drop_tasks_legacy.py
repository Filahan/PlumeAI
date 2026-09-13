"""Revision `0005_drop_tasks_legacy` must be idempotent and safe on a database that never
had a `tasks_legacy` table at all.

There is no ORM model for `tasks_legacy` (see `app.services.legacy_migration`), so
`create_all` never creates it — the test database this suite bootstraps from the models
starts without it, same as a fresh self-hosted install that never had the old `tasks`
table. These tests run the revision's real `upgrade()`, loaded through Alembic's own
script directory (mirrors `test_schema_migration.py`), so there is no second copy of the
DDL to drift.
"""

from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

import app as app_package


def _revision_module():
    """The `0005_drop_tasks_legacy` module, as Alembic itself would load it."""
    api_root = pathlib.Path(app_package.__file__).resolve().parent.parent
    config = Config(str(api_root / "alembic.ini"))
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(config).get_revision("0005_drop_tasks_legacy").module


def _run_upgrade(conn: sa.Connection) -> None:
    """Invoke the revision's `upgrade()` with the `alembic.op` proxy bound to `conn`."""
    module = _revision_module()
    context = MigrationContext.configure(conn)
    with Operations.context(context):
        module.upgrade()


async def test_upgrade_is_a_noop_when_tasks_legacy_never_existed(engine) -> None:
    """The exact shape of the test database bootstrapped from `create_all`."""
    async with engine.begin() as conn:
        assert not await conn.run_sync(lambda c: inspect(c).has_table("tasks_legacy"))
        await conn.run_sync(_run_upgrade)
        assert not await conn.run_sync(lambda c: inspect(c).has_table("tasks_legacy"))


async def test_upgrade_drops_tasks_legacy_when_present(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE tasks_legacy (id TEXT PRIMARY KEY)"))
        assert await conn.run_sync(lambda c: inspect(c).has_table("tasks_legacy"))

        await conn.run_sync(_run_upgrade)

        assert not await conn.run_sync(lambda c: inspect(c).has_table("tasks_legacy"))


async def test_upgrade_twice_in_a_row_is_safe(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE tasks_legacy (id TEXT PRIMARY KEY)"))

        await conn.run_sync(_run_upgrade)
        await conn.run_sync(_run_upgrade)

        assert not await conn.run_sync(lambda c: inspect(c).has_table("tasks_legacy"))


def test_downgrade_is_a_documented_noop() -> None:
    """Irreversible on purpose — see the revision's `downgrade()` docstring."""
    module = _revision_module()
    # Should not raise even with no bound `op` — it does nothing at all.
    module.downgrade()
