"""Persist usage tokens after each LLM stream completes. Used by chat + automations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageEntry


async def record_usage(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    conversation_id: str | None = None,
) -> None:
    if input_tokens <= 0 and output_tokens <= 0:
        return
    entry = UsageEntry(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(entry)
