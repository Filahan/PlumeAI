"""drop the standalone-chat tables — `messages` and `conversations`.

PlumeAI is an automation builder: the standalone chat feature (`POST /chat/stream` and
the `/conversations*` CRUD) is gone, replaced by the builder's assistant, which keeps its
transcript on `automations.assistant_messages`. Nothing in the app reads `conversations`
or `messages` any more, and the `Conversation`/`Message` ORM models were removed from
`Base.metadata` in the same change so `create_all` never recreates them.

`messages` is dropped first because it carries the conversation id (there was never a
real foreign key, but dropping the child first keeps the order meaningful either way).

`usage_entries.conversation_id` is deliberately **not** touched: it is a free-text
correlation id with no foreign key — automation runs write the run id into it and the
builder assistant writes the automation id — so it outlives the chat tables unchanged.

Guarded with `has_table` for the same reason `0003`/`0004`/`0005` are: this must be safe
on a database that never had chat tables, on one where the runtime path in
`app.main._apply_runtime_migrations` already dropped them (whichever path runs first
wins, the other is a no-op), and twice in a row.

Mirrors `app/main.py:_apply_runtime_migrations`, which performs the same guarded drops
for self-hosted users who never run `alembic upgrade` by hand.

Revision ID: 0006_drop_chat_tables
Revises: 0005_drop_tasks_legacy
Create Date: 2026-09-17 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_drop_chat_tables"
down_revision: Union[str, None] = "0005_drop_tasks_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Child first: `messages.conversation_id` points at `conversations.id`.
CHAT_TABLES = ("messages", "conversations")


def drop_schema(conn: sa.Connection) -> None:
    """Drop the chat tables if they're there. Extracted from `upgrade()` so the
    idempotency is directly testable rather than only observable by running Alembic twice
    (mirrors revisions `0003`/`0004`/`0005`).
    """
    inspector = sa.inspect(conn)
    for table in CHAT_TABLES:
        if inspector.has_table(table):
            op.drop_table(table)


def upgrade() -> None:
    drop_schema(op.get_bind())


def downgrade() -> None:
    # Irreversible on purpose: the chat feature no longer exists anywhere in the app, so
    # recreating empty `conversations`/`messages` shells would restore nothing usable —
    # there is no router, schema or model left to read them, and the conversations
    # themselves cannot be reconstructed. Restore a pre-`0006` backup if you need the
    # old transcripts.
    pass
