"""baseline — matches the existing drizzle schema.

This revision is **empty by design**: the tables already exist in the running database
(carried over from the drizzle-managed pgdata volume). We stamp this revision as `head`
so Alembic considers the schema "up to date" and future migrations diff against it.

If a fresh DB is needed, run `alembic upgrade head` on an empty DB → tables will be
created by SQLAlchemy.create_all() (called by app.main during startup, see Phase 1 lifespan).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-31 21:00:00
"""

from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: schema is created via SQLAlchemy.metadata.create_all on a fresh DB or already
    # exists on the carried-over pgdata volume. Future revisions provide real diffs.
    pass


def downgrade() -> None:
    pass
