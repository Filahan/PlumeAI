"""Schemas for chat conversations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import APISchema


class AttachmentRef(APISchema):
    id: str
    mime: str
    width: int
    height: int
    size: int


class MessagePayload(APISchema):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: int  # unix ms
    attachments: list[AttachmentRef] | None = None


class ConversationPayload(APISchema):
    id: str
    title: str
    provider: str
    model: str
    messages: list[MessagePayload] = Field(default_factory=list)
    created_at: int  # unix ms
    updated_at: int


class CreateConversationRequest(APISchema):
    id: str
    provider: str
    model: str


class AddMessageRequest(APISchema):
    id: str
    role: Literal["user", "assistant"]
    content: str
    attachments: list[AttachmentRef] | None = None


class AddMessageResponse(APISchema):
    first_user_message: bool


class UpdateMessageRequest(APISchema):
    chunk: str
    replace: bool = False


class UpdateConversationRequest(APISchema):
    title: str | None = None
    provider: str | None = None
    model: str | None = None
