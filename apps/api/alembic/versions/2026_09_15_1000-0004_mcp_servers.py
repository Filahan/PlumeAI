"""mcp servers — registered MCP servers and their cached tool listings.

Creates one table, `mcp_servers` (see `app.db.models.McpServer`). Guarded with
`has_table` for the same reason revision `0003_automations_v2` is: `app.main._ensure_schema`
runs `Base.metadata.create_all` on every startup, so by the time anyone runs
`alembic upgrade head` the table usually exists already and an unguarded `create_table`
would fail with `DuplicateTableError`. Safe on a fresh database, on one the app has
already bootstrapped, and twice in a row.

There is no counterpart in `_apply_runtime_migrations`: `create_all` covers this revision
completely (a new table, no altered columns), which is exactly what that function is for
adding to when a *column* appears on an existing table.

Revision ID: 0004_mcp_servers
Revises: 0003_automations_v2
Create Date: 2026-09-15 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_mcp_servers"
down_revision: Union[str, None] = "0003_automations_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_schema(conn: sa.Connection) -> None:
    """Create `mcp_servers` if it isn't there yet.

    Extracted from `upgrade()` so the idempotency is directly testable rather than only
    observable by running Alembic twice (mirrors revision 0003).
    """
    if sa.inspect(conn).has_table("mcp_servers"):
        return
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("transport", sa.Text(), nullable=False),
        # AES-GCM blob ({ciphertext, iv}) around {command, args, env} / {url, headers}.
        sa.Column("config_enc", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "allow_private_network", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "cached_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.UniqueConstraint("name", name="mcp_servers_name_key"),
    )


def upgrade() -> None:
    create_schema(op.get_bind())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mcp_servers")
