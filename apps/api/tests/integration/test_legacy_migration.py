"""`convert_legacy_tasks` — the one-way conversion of legacy `tasks` rows.

The legacy table no longer has an ORM model (that's the point: `create_all` must not
recreate it), so these tests build it with Core DDL the same way the migration reads it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import Automation, AutomationVersion, Run
from app.services.legacy_migration import LEGACY_STEP_NAME, convert_legacy_tasks

_legacy_metadata = sa.MetaData()

# The shape of `tasks` as it was before revision 0003 renamed it away.
legacy_tasks = sa.Table(
    "tasks",
    _legacy_metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("title", sa.Text),
    sa.Column("prompt", sa.Text, nullable=False),
    sa.Column("messages", JSONB, nullable=False, server_default="[]"),
    sa.Column("schedule", sa.Text, nullable=False, server_default="manual"),
    sa.Column("status", sa.Text, nullable=False, server_default="idle"),
    sa.Column("output", sa.Text),
    sa.Column("transcript", JSONB, nullable=False, server_default="[]"),
    sa.Column("runs", JSONB, nullable=False, server_default="[]"),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("error", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

CREATED_AT = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
RUN_ONE_START = 1_772_000_000_000
RUN_ONE_END = 1_772_000_030_000


def _task(**overrides) -> dict:
    base = {
        "title": None,
        "prompt": "",
        "messages": [],
        "schedule": "manual",
        "status": "idle",
        "output": None,
        "transcript": [],
        "runs": [],
        "provider": "openai",
        "model": "gpt-4o",
        "error": None,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def legacy_table(engine):
    """Recreate the legacy `tasks` table for the duration of one test."""
    async with engine.begin() as conn:
        await conn.run_sync(_legacy_metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(_legacy_metadata.drop_all)


async def _insert(engine, rows: list[dict]) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.insert(legacy_tasks), rows)


async def _convert(engine) -> int:
    async with engine.begin() as conn:
        return await conn.run_sync(convert_legacy_tasks)


async def test_converts_an_hourly_task_with_run_history(
    engine, session, legacy_table
) -> None:
    await _insert(
        engine,
        [
            _task(
                id="task-hourly",
                title="Hourly digest",
                prompt="Check the inbox and summarize it.",
                schedule="hourly",
                runs=[
                    {
                        "status": "succeeded",
                        "startedAt": RUN_ONE_START,
                        "endedAt": RUN_ONE_END,
                        "durationMs": 30_000,
                        "error": None,
                    },
                    {
                        "status": "failed",
                        "startedAt": RUN_ONE_START + 3_600_000,
                        "endedAt": RUN_ONE_END + 3_600_000,
                        "durationMs": 30_000,
                        "error": "boom",
                    },
                ],
            ),
            # An unfinished interview: no prompt means there is no step to run.
            _task(id="task-empty", schedule="manual", prompt=""),
        ],
    )

    assert await _convert(engine) == 1

    automations = (await session.execute(select(Automation))).scalars().all()
    assert [a.id for a in automations] == ["task-hourly"]
    automation = automations[0]
    assert automation.name == "Hourly digest"
    assert automation.enabled is True
    assert automation.assistant_messages == []
    assert automation.created_at == CREATED_AT

    doc = automation.document
    assert doc["trigger"] == {
        "type": "schedule",
        "settings": {"mode": "interval", "every_minutes": 60},
    }
    assert doc["model"] == {"provider": "openai", "model": "gpt-4o"}
    assert len(doc["steps"]) == 1
    step = doc["steps"][0]
    assert step["type"] == "ai"
    assert step["name"] == LEGACY_STEP_NAME
    assert step["settings"]["instructions"] == "Check the inbox and summarize it."
    assert step["settings"]["tools"] == []
    assert step["settings"]["output"] == {"mode": "text"}
    assert step["id"].startswith("step_")

    versions = (await session.execute(select(AutomationVersion))).scalars().all()
    assert len(versions) == 1
    assert versions[0].number == 1
    assert versions[0].created_by == "migration"
    assert versions[0].document == doc
    assert automation.current_version_id == versions[0].id

    runs = (
        (await session.execute(select(Run).order_by(Run.started_at))).scalars().all()
    )
    assert [r.status for r in runs] == ["succeeded", "failed"]
    assert all(r.trigger == "manual" for r in runs)
    assert all(r.automation_id == "task-hourly" for r in runs)
    assert all(r.version_id == versions[0].id for r in runs)
    assert runs[0].duration_ms == 30_000
    assert runs[0].started_at == datetime.fromtimestamp(
        RUN_ONE_START / 1000, tz=timezone.utc
    )
    assert runs[1].error == "boom"


async def test_conversion_is_idempotent(engine, session, legacy_table) -> None:
    await _insert(engine, [_task(id="task-1", prompt="Do a thing.", schedule="daily")])

    assert await _convert(engine) == 1
    assert await _convert(engine) == 0

    assert len((await session.execute(select(Automation))).scalars().all()) == 1
    assert len((await session.execute(select(AutomationVersion))).scalars().all()) == 1


async def test_schedule_mapping(engine, session, legacy_table) -> None:
    await _insert(
        engine,
        [
            _task(id="t-manual", prompt="p", schedule="manual"),
            _task(id="t-daily", prompt="p", schedule="daily"),
            _task(id="t-weekly", prompt="p", schedule="weekly"),
        ],
    )
    assert await _convert(engine) == 3

    by_id = {
        a.id: a.document["trigger"]
        for a in (await session.execute(select(Automation))).scalars().all()
    }
    assert by_id["t-manual"] == {"type": "manual"}
    assert by_id["t-daily"] == {
        "type": "schedule",
        "settings": {"mode": "cron", "cron": "0 9 * * *"},
    }
    assert by_id["t-weekly"] == {
        "type": "schedule",
        "settings": {"mode": "cron", "cron": "0 9 * * 1"},
    }
    # A schedule never carries both spellings — the document schema rejects that.
    for trigger in by_id.values():
        settings = trigger.get("settings", {})
        assert not ("cron" in settings and "every_minutes" in settings)


async def test_name_comes_from_the_title_then_from_the_prompt_head(
    engine,
    session,
    legacy_table,
) -> None:
    await _insert(
        engine,
        [
            _task(id="t-titled", title="  Weekly report  ", prompt="anything"),
            _task(id="t-untitled", prompt="x" * 200),
            _task(id="t-short", prompt="  Ship it.  "),
        ],
    )
    await _convert(engine)

    names = {
        a.id: a.name for a in (await session.execute(select(Automation))).scalars().all()
    }
    assert names["t-titled"] == "Weekly report"
    assert names["t-untitled"] == "x" * 60
    assert names["t-short"] == "Ship it."


async def test_unrepresentable_tasks_are_skipped(engine, session, legacy_table) -> None:
    """`ModelRef` only knows openai/anthropic — an openrouter task can't be a document."""
    await _insert(
        engine,
        [
            _task(id="t-openrouter", prompt="Do a thing.", provider="openrouter"),
            _task(id="t-ok", prompt="Do a thing.", provider="anthropic", model="claude-3"),
        ],
    )
    assert await _convert(engine) == 1
    ids = [a.id for a in (await session.execute(select(Automation))).scalars().all()]
    assert ids == ["t-ok"]


async def test_no_legacy_table_is_a_noop(engine) -> None:
    """The runtime path calls this unconditionally on databases that never had `tasks`."""
    assert await _convert(engine) == 0
