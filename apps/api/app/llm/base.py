"""Provider abstraction.

A `LLMProvider` knows how to stream a chat completion against an upstream LLM API. It
yields `AgentEvent` dicts the same way regardless of provider — the agent runner and the
chat endpoint don't care which provider is behind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.llm.events import AgentEvent

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    """Normalized chat message, provider-independent.

    - `role` always present.
    - `content` may be None when this message is a pure tool_call from the assistant.
    - `tool_calls` are present on assistant messages that requested tools.
    - `tool_call_id` is present on `role='tool'` messages (the result of a previous call).
    """

    role: Role
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None


class LLMProvider(Protocol):
    """All providers expose the same stream_chat shape."""

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream events for one round of chat completion.

        `tools` is the OpenAI function-calling schema list. Providers that natively support
        tools forward them; Anthropic translates internally.
        """
        ...  # pragma: no cover
