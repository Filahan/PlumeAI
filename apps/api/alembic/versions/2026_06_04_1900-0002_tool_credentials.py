"""tool_credentials column on settings.

Holds app-level credentials per provider namespace (e.g. "google" → encrypted blob of
client_id/client_secret). Set via the Tools UI. Mirrors the runtime ALTER TABLE in
app/main.py:_apply_runtime_migrations so either path keeps the schema in sync.

Revision ID: 0002_tool_credentials
Revises: 0001_baseline
Create Date: 2026-06-04 19:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_tool_credentials"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS "
        "tool_credentials JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS tool_credentials")
