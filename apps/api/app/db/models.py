"""SQLAlchemy ORM models.

`conversations`, `messages`, `settings` and `usage_entries` are a 1:1 mirror of the
original drizzle schema — same table names and column types, so the existing `pgdata`
volume is reused as-is.

The automation-builder tables (`automations`, `automation_versions`, `runs`,
`run_steps`) are new in revision `0003_automations_v2`, which also converts the legacy
`tasks` table into automations and renames it to `tasks_legacy`. The legacy `Task` model
is deliberately gone from `Base.metadata` so `create_all` never recreates that table;
the migration reaches the old rows through Core table definitions instead (see
`app.services.legacy_migration`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("messages_conversation_idx", "conversation_id"),
        Index("messages_timestamp_idx", "timestamp"),
    )


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    providers: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    default_model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Per-user OAuth tokens, keyed by integration name (e.g. "gmail" → {ciphertext, iv}).
    tools: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # App-level credentials, keyed by provider namespace (e.g. "google" → {ciphertext, iv}
    # → decrypts to {"client_id": ..., "client_secret": ...}). Set via the Tools UI.
    tool_credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # IANA timezone used to resolve schedule triggers that don't carry one of their own.
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")


class UsageEntry(Base):
    __tablename__ = "usage_entries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("usage_timestamp_idx", "timestamp"),
        Index("usage_provider_idx", "provider"),
    )


# ─── automation builder ──────────────────────────────────────────────────────────────


class Automation(Base):
    """One automation: its current *draft* document plus denormalized last-run state.

    `document` is the canonical dict form of an `AutomationDocument` (see
    `app.services.documents.dump_document`). It is the working draft and always matches
    the version pointed at by `current_version_id` — a new version row is only written
    when the document actually changes.
    """

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Transcript of the builder assistant conversation ({role, content, ...} dicts).
    assistant_messages: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    last_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("automations_updated_idx", "updated_at"),)


class AutomationVersion(Base):
    """An immutable snapshot of an automation document, numbered from 1."""

    __tablename__ = "automation_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("automations.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # user | assistant | json | migration | restore
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("automation_id", "number", name="automation_versions_number_uq"),
        Index("automation_versions_automation_idx", "automation_id"),
    )


class Run(Base):
    """One execution of one automation version."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("automations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL rather than CASCADE: pruning an old version must not delete its run history.
    version_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("automation_versions.id", ondelete="SET NULL"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)  # manual | schedule | test
    # queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    stopped_by_step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    # Newest-first listing per automation — DESC so the common `ORDER BY created_at DESC`
    # scan is a plain forward index read.
    __table_args__ = (
        Index("runs_automation_created_idx", "automation_id", text("created_at DESC")),
    )


class RunStep(Base):
    """Per-step state of a run, created up front (one `pending` row per document step)."""

    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(Text, nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | running | succeeded | failed | skipped | cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    resolved_input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, server_default="[]")
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("run_steps_run_idx", "run_id", "index"),)
