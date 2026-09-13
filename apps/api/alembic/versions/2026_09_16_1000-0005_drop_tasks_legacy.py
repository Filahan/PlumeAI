"""drop tasks_legacy — the old pre-builder `tasks` table, kept around read-only since
`0003_automations_v2` renamed it, is no longer needed by anything in the app.

Revision `0003_automations_v2` converted every row of the legacy `tasks` table into an
`automations` row (see `app.services.legacy_migration.convert_legacy_tasks`) and only
*then* renamed `tasks` to `tasks_legacy` — so by construction, any database that has a
`tasks_legacy` table already has that data duplicated into `automations`. Nothing reads
`tasks_legacy` any more (there is no ORM model for it at all), so this drops it.

Guarded with `has_table` for the same reason `0003`/`0004` are: this must be safe to run
on a database that never had a legacy `tasks` table (nothing to drop), one that already
had `tasks_legacy` dropped by the runtime path in `app.main._apply_runtime_migrations`
(whichever path runs first wins, the other is a no-op), and twice in a row.

Mirrors `app/main.py:_apply_runtime_migrations`, which performs the same guarded drop
for self-hosted users who never run `alembic upgrade` by hand.

Revision ID: 0005_drop_tasks_legacy
Revises: 0004_mcp_servers
Create Date: 2026-09-16 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_drop_tasks_legacy"
down_revision: Union[str, None] = "0004_mcp_servers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def drop_schema(conn: sa.Connection) -> None:
    """Drop `tasks_legacy` if it's there. Extracted from `upgrade()` so the idempotency
    is directly testable rather than only observable by running Alembic twice (mirrors
    revisions `0003`/`0004`).
    """
    if not sa.inspect(conn).has_table("tasks_legacy"):
        return
    op.drop_table("tasks_legacy")


def upgrade() -> None:
    drop_schema(op.get_bind())


def downgrade() -> None:
    # Irreversible on purpose: `tasks_legacy` was already a read-only copy of data that
    # lives in `automations` (see module docstring), so there is nothing to restore —
    # recreating an empty `tasks_legacy` shell would be actively misleading (it would
    # look like the legacy data still existed, but every row of it is in `automations`).
    # If you ever need the pre-conversion shape back, restore a pre-`0003` backup instead.
    pass
