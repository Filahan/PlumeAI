"""automation builder v2 — automations, versions, runs, run_steps.

Creates the four builder tables, adds `settings.timezone`, converts every legacy `tasks`
row into an automation (see `app.services.legacy_migration`) and finally renames `tasks`
to `tasks_legacy` so the old data stays readable but nothing writes to it any more.

Mirrors `app/main.py:_apply_runtime_migrations`, which performs the same timezone ALTER
and the same convert+rename for self-hosted users who never run Alembic by hand. Both
paths are guarded the same way, so whichever runs first wins and the other is a no-op.

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


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
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
    op.create_index("automations_updated_idx", "automations", ["updated_at"])

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
    op.create_index(
        "automation_versions_automation_idx", "automation_versions", ["automation_id"]
    )

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
    op.execute(
        "CREATE INDEX runs_automation_created_idx "
        "ON runs (automation_id, created_at DESC)"
    )

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
    op.create_index("run_steps_run_idx", "run_steps", ["run_id", "index"])

    op.execute(
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
        "timezone TEXT NOT NULL DEFAULT 'UTC'"
    )

    convert_legacy_tasks(op.get_bind())
    op.execute(RENAME_TASKS)


def downgrade() -> None:
    op.execute(RENAME_TASKS_BACK)
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS timezone")
    op.drop_table("run_steps")
    op.drop_table("runs")
    op.drop_table("automation_versions")
    op.drop_table("automations")
