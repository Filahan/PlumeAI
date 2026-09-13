"""Chat streaming request shape. Matches the existing TypeScript client payload."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from app.schemas.base import APISchema


class TextPart(APISchema):
    type: Literal["text"]
    text: str


class ImagePart(APISchema):
    type: Literal["image"]
    mime: str
    base64: str  # raw base64 (no data: prefix)


Part = Annotated[Union[TextPart, ImagePart], Field(discriminator="type")]
Content = str | list[Part]


class HistoryTurn(APISchema):
    role: Literal["user", "assistant"]
    content: Content


class ChatStreamRequest(APISchema):
    provider: Literal["openai", "anthropic"]
    model: str
    history: list[HistoryTurn] = Field(default_factory=list)
    new_message: Content
    conversation_id: str | None = None
