"""Usage entry schemas — read-only view of the usage_entries table."""

from __future__ import annotations

from app.schemas.base import APISchema


class UsageEntryPayload(APISchema):
    timestamp: int  # unix ms
    # Correlation id, not a foreign key: run id for runs, automation id for the
    # builder assistant. See `app.services.usage.record_usage`.
    conversation_id: str | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
