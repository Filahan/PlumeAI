"""Usage entry schemas — read-only view of the usage_entries table."""

from __future__ import annotations

from app.schemas.base import APISchema


class UsageEntryPayload(APISchema):
    timestamp: int  # unix ms
    conversation_id: str | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
