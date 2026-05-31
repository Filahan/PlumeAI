"""SQLAlchemy ORM models, 1:1 mirror of the existing drizzle schema.

Tables are named identically and use the same column types so the existing `pgdata` volume
can be reused as-is (no data migration needed). Alembic is stamped against the baseline
revision that matches this state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, Text
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
    tools: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    messages: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    schedule: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="manual"
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="idle"
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    runs: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("tasks_created_idx", "created_at"),)


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
