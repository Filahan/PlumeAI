"""Usage dashboard — list usage entries for the per-model breakdown + chart."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.base import get_session
from app.db.models import UsageEntry
from app.schemas.usage import UsageEntryPayload
from app.utils import to_ms as _dt_ms

router = APIRouter(prefix="/usage", tags=["usage"])

DBSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[UsageEntryPayload], response_model_by_alias=True)
async def list_usage(user: CurrentUser, session: DBSession) -> list[UsageEntryPayload]:
    rows = (
        await session.execute(select(UsageEntry).order_by(UsageEntry.timestamp.asc()))
    ).scalars().all()
    return [
        UsageEntryPayload(
            timestamp=_dt_ms(r.timestamp),
            conversation_id=r.conversation_id,
            provider=r.provider,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        for r in rows
    ]
