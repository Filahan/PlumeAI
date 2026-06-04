"""Chat conversations + their messages — CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.base import get_session
from app.db.models import Conversation, Message
from app.errors import NotFound
from app.schemas.conversations import (
    AddMessageRequest,
    AddMessageResponse,
    ConversationPayload,
    CreateConversationRequest,
    MessagePayload,
    UpdateConversationRequest,
    UpdateMessageRequest,
)
from app.utils import to_ms as _ms

router = APIRouter(prefix="/conversations", tags=["conversations"])

DBSession = Annotated[AsyncSession, Depends(get_session)]


async def _get_conv(session: AsyncSession, conv_id: str) -> Conversation:
    row = (
        await session.execute(select(Conversation).where(Conversation.id == conv_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Conversation {conv_id} not found.")
    return row


# ─── Conversations CRUD ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[ConversationPayload], response_model_by_alias=True)
async def list_conversations(user: CurrentUser, session: DBSession) -> list[ConversationPayload]:
    convs = (
        await session.execute(select(Conversation).order_by(Conversation.updated_at.desc()))
    ).scalars().all()
    if not convs:
        return []
    ids = [c.id for c in convs]
    msgs = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id.in_(ids))
            .order_by(Message.timestamp.asc())
        )
    ).scalars().all()
    by_conv: dict[str, list[MessagePayload]] = {}
    for m in msgs:
        by_conv.setdefault(m.conversation_id, []).append(
            MessagePayload(
                id=m.id,
                role=m.role,  # type: ignore[arg-type]
                content=m.content,
                timestamp=_ms(m.timestamp),
                attachments=m.attachments,  # type: ignore[arg-type]
            )
        )
    return [
        ConversationPayload(
            id=c.id,
            title=c.title,
            provider=c.provider,
            model=c.model,
            messages=by_conv.get(c.id, []),
            created_at=_ms(c.created_at),
            updated_at=_ms(c.updated_at),
        )
        for c in convs
    ]


@router.post("", response_model=ConversationPayload, response_model_by_alias=True)
async def create_conversation(
    body: CreateConversationRequest, user: CurrentUser, session: DBSession
) -> ConversationPayload:
    row = Conversation(
        id=body.id,
        title="Nouvelle conversation",
        provider=body.provider,
        model=body.model,
    )
    session.add(row)
    await session.flush()
    return ConversationPayload(
        id=row.id,
        title=row.title,
        provider=row.provider,
        model=row.model,
        messages=[],
        created_at=_ms(row.created_at),
        updated_at=_ms(row.updated_at),
    )


@router.patch("/{conv_id}", response_model=ConversationPayload, response_model_by_alias=True)
async def update_conversation(
    conv_id: str,
    body: UpdateConversationRequest,
    user: CurrentUser,
    session: DBSession,
) -> ConversationPayload:
    row = await _get_conv(session, conv_id)
    if body.title is not None and body.title:
        row.title = body.title
    if body.provider is not None:
        row.provider = body.provider
    if body.model is not None:
        row.model = body.model
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return ConversationPayload(
        id=row.id,
        title=row.title,
        provider=row.provider,
        model=row.model,
        messages=[],
        created_at=_ms(row.created_at),
        updated_at=_ms(row.updated_at),
    )


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str, user: CurrentUser, session: DBSession
) -> dict[str, str]:
    # Postgres FK cascade deletes messages too.
    await session.execute(delete(Conversation).where(Conversation.id == conv_id))
    return {"status": "ok"}


# ─── Messages ────────────────────────────────────────────────────────────────────────


@router.post("/{conv_id}/messages", response_model=AddMessageResponse, response_model_by_alias=True)
async def add_message(
    conv_id: str,
    body: AddMessageRequest,
    user: CurrentUser,
    session: DBSession,
) -> AddMessageResponse:
    # Check if this is the first user message (auto-title)
    existing = (
        await session.execute(
            select(Message.role).where(Message.conversation_id == conv_id)
        )
    ).scalars().all()
    is_first_user = body.role == "user" and all(r != "user" for r in existing)

    now = datetime.now(timezone.utc)
    msg = Message(
        id=body.id,
        conversation_id=conv_id,
        role=body.role,
        content=body.content,
        attachments=[a.model_dump(by_alias=True) for a in body.attachments] if body.attachments else None,
        timestamp=now,
    )
    session.add(msg)

    conv = await _get_conv(session, conv_id)
    conv.updated_at = now
    if is_first_user:
        title = body.content[:40] + ("..." if len(body.content) > 40 else "")
        conv.title = title

    await session.flush()
    return AddMessageResponse(first_user_message=is_first_user)


@router.patch("/{conv_id}/messages/{msg_id}")
async def update_message(
    conv_id: str,
    msg_id: str,
    body: UpdateMessageRequest,
    user: CurrentUser,
    session: DBSession,
) -> dict[str, str]:
    msg = (
        await session.execute(
            select(Message).where(
                Message.id == msg_id, Message.conversation_id == conv_id
            )
        )
    ).scalar_one_or_none()
    if msg is None:
        raise NotFound(f"Message {msg_id} not found.")
    msg.content = body.chunk if body.replace else msg.content + body.chunk
    conv = await _get_conv(session, conv_id)
    conv.updated_at = datetime.now(timezone.utc)
    return {"status": "ok"}
