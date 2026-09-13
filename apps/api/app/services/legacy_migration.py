"""One-way conversion of the legacy `tasks` table into automations.

The old automations feature stored a free-text agent prompt plus a coarse schedule
(`manual`/`hourly`/`daily`/`weekly`) on a single `tasks` row. The builder replaces that
with an `AutomationDocument`: a trigger and an ordered list of typed steps. Every legacy
task becomes a one-step automation whose single `ai` step carries the old prompt, so
nothing a user built is lost — it just shows up in the builder as a document they can
now edit step by step.

Why Core and not the ORM: this runs from two places — the Alembic revision
`0003_automations_v2` (a plain sync `Connection`) and the runtime migration in
`app.main` (via `await conn.run_sync(convert_legacy_tasks)`). Both need to read a table
(`tasks`) that no longer has an ORM model at all, and Alembic must not depend on the
current shape of `app.db.models`. Core `sa.table(...)` definitions pin exactly the
columns this conversion reads and writes, frozen at the time the migration was written.

Idempotent: a legacy task whose id already exists in `automations` is skipped, so
running the converter twice (Alembic *and* the runtime path, or a retried startup) is
harmless.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection

from app.schemas.documents import AutomationDocument
from app.services.documents import dump_document, new_step_id

log = structlog.get_logger("app.legacy_migration")

DEFAULT_NAME = "Untitled automation"
NAME_FROM_PROMPT_CHARS = 60
LEGACY_STEP_NAME = "Run the automation"

# --- frozen Core definitions of the tables this conversion touches ----------------------

tasks_table = sa.table(
    "tasks",
    sa.column("id", sa.Text),
    sa.column("title", sa.Text),
    sa.column("prompt", sa.Text),
    sa.column("schedule", sa.Text),
    sa.column("runs", JSONB),
    sa.column("provider", sa.Text),
    sa.column("model", sa.Text),
    sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.column("updated_at", sa.TIMESTAMP(timezone=True)),
)

automations_table = sa.table(
    "automations",
    sa.column("id", sa.Text),
    sa.column("name", sa.Text),
    sa.column("description", sa.Text),
    sa.column("enabled", sa.Boolean),
    sa.column("document", JSONB),
    sa.column("current_version_id", sa.Text),
    sa.column("assistant_messages", JSONB),
    sa.column("last_run_id", sa.Text),
    sa.column("last_run_status", sa.Text),
    sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    sa.column("updated_at", sa.TIMESTAMP(timezone=True)),
)

automation_versions_table = sa.table(
    "automation_versions",
    sa.column("id", sa.Text),
    sa.column("automation_id", sa.Text),
    sa.column("number", sa.Integer),
    sa.column("document", JSONB),
    sa.column("created_by", sa.Text),
    sa.column("created_at", sa.TIMESTAMP(timezone=True)),
)

runs_table = sa.table(
    "runs",
    sa.column("id", sa.Text),
    sa.column("automation_id", sa.Text),
    sa.column("version_id", sa.Text),
    sa.column("trigger", sa.Text),
    sa.column("status", sa.Text),
    sa.column("error", sa.Text),
    sa.column("input_tokens", sa.Integer),
    sa.column("output_tokens", sa.Integer),
    sa.column("started_at", sa.TIMESTAMP(timezone=True)),
    sa.column("ended_at", sa.TIMESTAMP(timezone=True)),
    sa.column("duration_ms", sa.Integer),
    sa.column("created_at", sa.TIMESTAMP(timezone=True)),
)

# --- schedule mapping --------------------------------------------------------------------

# The old scheduler had four fixed choices; "daily"/"weekly" fired at 09:00 server time.
# Timezone is intentionally omitted — the document falls back to the app-level
# `settings.timezone` when a schedule doesn't carry one.
_TRIGGERS: dict[str, dict[str, Any]] = {
    "manual": {"type": "manual"},
    "hourly": {"type": "schedule", "settings": {"mode": "interval", "every_minutes": 60}},
    "daily": {"type": "schedule", "settings": {"mode": "cron", "cron": "0 9 * * *"}},
    "weekly": {"type": "schedule", "settings": {"mode": "cron", "cron": "0 9 * * 1"}},
}

_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def _name_for(title: str | None, prompt: str) -> str:
    if title and title.strip():
        return title.strip()
    head = (prompt or "").strip()[:NAME_FROM_PROMPT_CHARS].strip()
    return head or DEFAULT_NAME


def _provider_for(provider: str | None, model: str | None) -> dict[str, str] | None:
    """`ModelRef` only accepts openai/anthropic; anything else (e.g. openrouter) can't be
    represented in a document, so the task is skipped rather than silently re-provider'd."""
    if provider not in {"openai", "anthropic"} or not model:
        return None
    return {"provider": provider, "model": model}


def _build_document(row: sa.Row) -> dict[str, Any] | None:
    """The legacy task as a canonical document dict, or None if it can't be represented."""
    prompt = (row.prompt or "").strip()
    if not prompt:
        # An unfinished interview: no prompt means there is no step to run and the
        # document would fail `instructions: min_length=1`.
        return None

    model = _provider_for(row.provider, row.model)
    if model is None:
        return None

    raw = {
        "name": _name_for(row.title, prompt),
        "description": "",
        "model": model,
        "trigger": _TRIGGERS.get(row.schedule or "manual", _TRIGGERS["manual"]),
        "steps": [
            {
                "id": new_step_id(),
                "name": LEGACY_STEP_NAME,
                "type": "ai",
                "settings": {
                    "instructions": prompt,
                    "tools": [],
                    "output": {"mode": "text"},
                },
                "valid": True,
            }
        ],
    }
    try:
        return dump_document(AutomationDocument.model_validate(raw))
    except Exception:  # noqa: BLE001 — a malformed legacy row must not abort the migration
        log.warning("legacy_task_invalid_document", task_id=row.id, exc_info=True)
        return None


def _ms_to_dt(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _legacy_runs(row: sa.Row, automation_id: str, version_id: str) -> list[dict[str, Any]]:
    """Flatten the legacy `runs` JSONB array into `runs` rows.

    Entries were written by `TaskRun.model_dump(by_alias=True)` (camelCase), but very old
    rows may still be snake_case — read both spellings.
    """
    out: list[dict[str, Any]] = []
    for entry in row.runs or []:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status not in _RUN_STATUSES:
            status = "failed"
        started_at = _ms_to_dt(entry.get("startedAt", entry.get("started_at")))
        ended_at = _ms_to_dt(entry.get("endedAt", entry.get("ended_at")))
        duration = entry.get("durationMs", entry.get("duration_ms"))
        out.append(
            {
                "id": uuid.uuid4().hex,
                "automation_id": automation_id,
                "version_id": version_id,
                "trigger": "manual",
                "status": status,
                "error": entry.get("error"),
                "input_tokens": 0,
                "output_tokens": 0,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": duration if isinstance(duration, int) else None,
                "created_at": started_at or row.created_at or datetime.now(timezone.utc),
            }
        )
    return out


def convert_legacy_tasks(conn: Connection) -> int:
    """Convert every legacy `tasks` row into an automation + version #1 + run history.

    Returns the number of automations created. A no-op (returns 0) when `tasks` doesn't
    exist, and skips ids that are already present in `automations`.
    """
    inspector = sa.inspect(conn)
    if not inspector.has_table("tasks"):
        return 0

    task_rows = conn.execute(sa.select(tasks_table)).fetchall()
    if not task_rows:
        return 0

    existing = {
        r[0] for r in conn.execute(sa.select(automations_table.c.id)).fetchall()
    }

    created = 0
    for row in task_rows:
        if row.id in existing:
            continue
        document = _build_document(row)
        if document is None:
            log.info("legacy_task_skipped", task_id=row.id)
            continue

        now = datetime.now(timezone.utc)
        created_at = row.created_at or now
        version_id = uuid.uuid4().hex

        conn.execute(
            sa.insert(automations_table).values(
                id=row.id,
                name=document["name"],
                description=document.get("description", ""),
                enabled=True,
                document=document,
                current_version_id=version_id,
                assistant_messages=[],
                last_run_id=None,
                last_run_status=None,
                created_at=created_at,
                updated_at=row.updated_at or created_at,
            )
        )
        conn.execute(
            sa.insert(automation_versions_table).values(
                id=version_id,
                automation_id=row.id,
                number=1,
                document=document,
                created_by="migration",
                created_at=created_at,
            )
        )
        run_values = _legacy_runs(row, row.id, version_id)
        if run_values:
            conn.execute(sa.insert(runs_table), run_values)
        created += 1

    log.info("legacy_tasks_converted", count=created, total=len(task_rows))
    return created
