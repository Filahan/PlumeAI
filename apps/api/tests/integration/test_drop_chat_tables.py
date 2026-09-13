"""Revision `0006_drop_chat_tables` must be idempotent and safe on a database that never
had the standalone-chat tables at all.

The `Conversation`/`Message` models are gone from `Base.metadata` (the chat feature was
replaced by the builder's assistant), so `create_all` never creates `conversations` or
`messages` — the test database this suite bootstraps from the models starts without them,
same as a fresh self-hosted install. These tests run the revision's real `upgrade()`,
loaded through Alembic's own script directory (mirrors `test_schema_migration.py` and
`test_drop_tasks_legacy.py`), so there is no second copy of the DDL to drift.

The single-head assertion lives here rather than in its own module because `0006` is the
head: a revision added without a `down_revision` (or pointed at the wrong one) would
silently branch the history and `alembic upgrade head` would start failing.
"""

from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

import app as app_package

CHAT_TABLES = ("messages", "conversations")


def _script_directory() -> ScriptDirectory:
    api_root = pathlib.Path(app_package.__file__).resolve().parent.parent
    return ScriptDirectory.from_config(Config(str(api_root / "alembic.ini")))


def _revision_module():
    """The `0006_drop_chat_tables` module, as Alembic itself would load it."""
    return _script_directory().get_revision("0006_drop_chat_tables").module


def _run_upgrade(conn: sa.Connection) -> None:
    """Invoke the revision's `upgrade()` with the `alembic.op` proxy bound to `conn`."""
    module = _revision_module()
    context = MigrationContext.configure(conn)
    with Operations.context(context):
        module.upgrade()


def _create_chat_tables(conn: sa.Connection) -> None:
    """The pre-`0006` shape of the two tables, as `create_all` used to build them."""
    conn.execute(
        text(
            "CREATE TABLE conversations ("
            "id TEXT PRIMARY KEY, title TEXT NOT NULL, provider TEXT NOT NULL, "
            "model TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE messages ("
            "id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, "
            "content TEXT NOT NULL, attachments JSONB, "
            "timestamp TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    conn.execute(text("CREATE INDEX messages_conversation_idx ON messages (conversation_id)"))
    conn.execute(text("CREATE INDEX messages_timestamp_idx ON messages (timestamp)"))


def _has(conn: sa.Connection, table: str) -> bool:
    return inspect(conn).has_table(table)


async def test_upgrade_is_a_noop_when_the_chat_tables_never_existed(engine) -> None:
    """The exact shape of the test database bootstrapped from `create_all`."""
    async with engine.begin() as conn:
        for table in CHAT_TABLES:
            assert not await conn.run_sync(_has, table)
        await conn.run_sync(_run_upgrade)
        for table in CHAT_TABLES:
            assert not await conn.run_sync(_has, table)


async def test_upgrade_drops_both_chat_tables_when_present(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_create_chat_tables)
        for table in CHAT_TABLES:
            assert await conn.run_sync(_has, table)

        await conn.run_sync(_run_upgrade)

        for table in CHAT_TABLES:
            assert not await conn.run_sync(_has, table)


async def test_upgrade_twice_in_a_row_is_safe(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_create_chat_tables)

        await conn.run_sync(_run_upgrade)
        await conn.run_sync(_run_upgrade)

        for table in CHAT_TABLES:
            assert not await conn.run_sync(_has, table)


async def test_upgrade_leaves_usage_entries_alone(engine) -> None:
    """`usage_entries.conversation_id` is a correlation id, not a chat foreign key: runs
    write the run id into it and the builder assistant writes the automation id."""
    async with engine.begin() as conn:
        await conn.run_sync(_create_chat_tables)
        await conn.execute(
            text(
                "INSERT INTO usage_entries "
                "(id, conversation_id, provider, model, input_tokens, output_tokens) "
                "VALUES ('u1', 'run_123', 'openai', 'gpt-4o-mini', 10, 5)"
            )
        )

        await conn.run_sync(_run_upgrade)

        assert await conn.run_sync(_has, "usage_entries")
        row = (
            await conn.execute(
                text("SELECT conversation_id FROM usage_entries WHERE id = 'u1'")
            )
        ).scalar()
        assert row == "run_123"


def test_downgrade_is_a_documented_noop() -> None:
    """Irreversible on purpose — see the revision's `downgrade()` docstring."""
    module = _revision_module()
    # Should not raise even with no bound `op` — it does nothing at all.
    module.downgrade()


def test_the_migration_history_has_a_single_head() -> None:
    assert list(_script_directory().get_heads()) == ["0006_drop_chat_tables"]
