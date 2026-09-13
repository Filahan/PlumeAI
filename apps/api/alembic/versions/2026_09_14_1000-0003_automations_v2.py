"""automation builder v2 — automations, versions, runs, run_steps.

Creates the four builder tables, adds `settings.timezone` and `automations.valid`,
converts every legacy `tasks` row into an automation (see
`app.services.legacy_migration`) and finally renames `tasks` to `tasks_legacy` so the old
data stays readable but nothing writes to it any more.

Mirrors `app/main.py:_apply_runtime_migrations`, which performs the same ALTERs and the
same convert+rename for self-hosted users who never run Alembic by hand. Both paths are
guarded the same way, so whichever runs first wins and the other is a no-op.

Every statement in `upgrade()` is guarded, because on this project Alembic is *not* the
only thing that creates tables: `app.main._ensure_schema` runs `Base.metadata.create_all`
on every startup, so by the time anyone runs `alembic upgrade head` the four tables
usually already exist. An unguarded `create_table` would fail there with
`DuplicateTableError`. `upgrade()` is therefore safe to run on a fresh database, on one
the app has already bootstrapped, and twice in a row.

Revision ID: 0003_automations_v2
Revises: 0002_tool_credentials
Create Date: 2026-09-14 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.legacy_migration import convert_legacy_tasks

revision: str = "0003_automations_v2"
down_revision: Union[str, None] = "0002_tool_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `tasks` is only renamed when there is something to rename and the target name is free —
# otherwise a re-run (or the runtime path having gone first) would error out.
RENAME_TASKS = """
DO $$
BEGIN
    IF to_regclass('public.tasks') IS NOT NULL
       AND to_regclass('public.tasks_legacy') IS NULL THEN
        ALTER TABLE tasks RENAME TO tasks_legacy;
    END IF;
END $$;
"""

RENAME_TASKS_BACK = """
DO $$
BEGIN
    IF to_regclass('public.tasks_legacy') IS NOT NULL
       AND to_regclass('public.tasks') IS NULL THEN
        ALTER TABLE tasks_legacy RENAME TO tasks;
    END IF;
END $$;
"""

# Columns added to tables that may predate them — `create_all` on an older build of the
# app produced `automations` without `valid`, and `settings` without `timezone`.
ADD_COLUMNS = (
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC'",
    "ALTER TABLE automations ADD COLUMN IF NOT EXISTS valid BOOLEAN NOT NULL DEFAULT true",
)

# Only one run of an automation may be `queued`/`running` at a time (see `Run` in
# `app.db.models`). A database that predates the index may hold rows that violate it —
# a crash leaves runs `running` forever — so the duplicates are failed first. Nothing is
# executing them by the time a migration runs, which is exactly what
# `app.services.runs.mark_orphaned_runs_failed` does on every startup.
DEMOTE_DUPLICATE_ACTIVE_RUNS = """
UPDATE runs SET status = 'failed', error = 'Interrupted by server restart', ended_at = now()
WHERE id IN (
    SELECT id FROM (
        SELECT id, row_number() OVER (
            PARTITION BY automation_id ORDER BY created_at DESC
        ) AS rn
        FROM runs WHERE status IN ('queued', 'running')
    ) ranked WHERE rn > 1
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS automations_updated_idx ON automations (updated_at)",
    "CREATE INDEX IF NOT EXISTS automation_versions_automation_idx "
    "ON automation_versions (automation_id)",
    "CREATE INDEX IF NOT EXISTS runs_automation_created_idx "
    "ON runs (automation_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS run_steps_run_idx ON run_steps (run_id, index)",
    "CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active_per_automation "
    "ON runs (automation_id) WHERE status IN ('queued', 'running')",
)


def _create_automations(conn: sa.Connection) -> None:
    if sa.inspect(conn).has_table("automations"):
        return
    op.create_table(
        "automations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version_id", sa.Text(), nullable=True),
        sa.Column(
            "assistant_messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("last_run_id", sa.Text(), nullable=True),
        sa.Column("last_run_status", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_automation_versions(conn: sa.Connection) -> None:
    if sa.inspect(conn).has_table("automation_versions"):
        return
    op.create_table(
        "automation_versions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("automation_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "number", name="automation_versions_number_uq"),
    )


def _create_runs(conn: sa.Connection) -> None:
    if sa.inspect(conn).has_table("runs"):
        return
    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("automation_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("stopped_by_step_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["automation_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_run_steps(conn: sa.Connection) -> None:
    if sa.inspect(conn).has_table("run_steps"):
        return
    op.create_table(
        "run_steps",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "trace",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def create_schema(conn: sa.Connection) -> None:
    """Bring the builder schema up to date, creating only what is missing.

    Extracted from `upgrade()` so the idempotency this revision depends on is directly
    testable (see `tests/integration/test_schema_migration.py`) instead of only being
    observable by running Alembic twice.
    """
    _create_automations(conn)
    _create_automation_versions(conn)
    _create_runs(conn)
    _create_run_steps(conn)
    for statement in ADD_COLUMNS:
        op.execute(statement)
    op.execute(DEMOTE_DUPLICATE_ACTIVE_RUNS)
    for statement in INDEXES:
        op.execute(statement)


def upgrade() -> None:
    conn = op.get_bind()
    create_schema(conn)
    convert_legacy_tasks(conn)
    op.execute(RENAME_TASKS)


def downgrade() -> None:
    op.execute(RENAME_TASKS_BACK)
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS timezone")
    op.execute("DROP INDEX IF EXISTS runs_one_active_per_automation")
    op.execute("DROP TABLE IF EXISTS run_steps")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS automation_versions")
    op.execute("DROP TABLE IF EXISTS automations")
