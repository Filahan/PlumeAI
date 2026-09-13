"""add `usage_entries.source`.

Distinguishes what `usage_entries.conversation_id` actually holds: "run" when it's an
automation run id (written by `app.services.executor`), "assistant" when it's an
automation id (written by `app.services.assistant`). Both are 32-hex uuids and were
previously indistinguishable from each other — see `app.services.usage.record_usage`.

Nullable, no default: existing rows are left as `NULL` rather than guessed at, and the
usage dashboard falls back to the old ambiguous "N sources" wording for them (see
`apps/web/src/app/usage/page.tsx`).

`ADD COLUMN IF NOT EXISTS` is itself the idempotency guard — same style as
`0002_tool_credentials` — safe on a database this has already run against, and mirrors
the runtime path in `app.main._apply_runtime_migrations`.

Revision ID: 0007_usage_entry_source
Revises: 0006_drop_chat_tables
Create Date: 2026-09-18 10:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007_usage_entry_source"
down_revision: Union[str, None] = "0006_drop_chat_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE usage_entries ADD COLUMN IF NOT EXISTS source TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE usage_entries DROP COLUMN IF EXISTS source")
