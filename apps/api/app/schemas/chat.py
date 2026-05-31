"""Chat streaming request shape. Matches the existing TypeScript client payload."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import APISchema


class HistoryTurn(APISchema):
    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(APISchema):
    provider: Literal["openai", "anthropic", "openrouter"]
    model: str
    history: list[HistoryTurn] = Field(default_factory=list)
    new_message: str
    conversation_id: str | None = None
