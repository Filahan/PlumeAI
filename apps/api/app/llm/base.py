"""Provider abstraction.

A `LLMProvider` knows how to stream a chat completion against an upstream LLM API. It
yields `AgentEvent` dicts the same way regardless of provider — the agent runner and the
chat endpoint don't care which provider is behind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.errors import BadRequest
from app.llm.events import AgentEvent

Role = Literal["system", "user", "assistant", "tool"]

# What a caller may pass as `tool_choice`: the OpenAI string modes ("auto" / "none" /
# "required") or a dict naming one tool. Providers translate to their own wire format.
ToolChoice = str | dict[str, Any]

ToolChoiceMode = Literal["auto", "none", "required", "tool"]

# Aliases we accept on input so callers can hand us either vendor's spelling.
_MODE_ALIASES: dict[str, ToolChoiceMode] = {
    "auto": "auto",
    "none": "none",
    "required": "required",
    "any": "required",  # Anthropic's spelling of "required"
}


@dataclass
class ChatMessage:
    """Normalized chat message, provider-independent.

    - `role` always present.
    - `content` is either a plain string OR a list of parts (`{type: 'text'|'image', ...}`)
      for multimodal messages. Provider clients translate to their native wire format.
    - `tool_calls` are present on assistant messages that requested tools.
    - `tool_call_id` is present on `role='tool'` messages (the result of a previous call).
    """

    role: Role
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class NormalizedToolChoice:
    """Provider-independent tool_choice: a mode, plus a tool name when mode is `tool`."""

    mode: ToolChoiceMode
    tool: str | None = None


def normalize_tool_choice(tool_choice: ToolChoice | None) -> NormalizedToolChoice | None:
    """Normalize any accepted `tool_choice` spelling, or raise `BadRequest`.

    Accepted: `None` (provider default), the strings `"auto"` / `"none"` / `"required"`
    (plus Anthropic's `"any"` for required), `{"type": "function", "function": {"name": n}}`,
    Anthropic's `{"type": "tool", "name": n}`, and a bare `{"type": <mode>}`.

    Returns `None` for `None` so providers can omit the field entirely rather than sending
    a default the upstream API would treat differently.
    """
    if tool_choice is None:
        return None

    if isinstance(tool_choice, str):
        mode = _MODE_ALIASES.get(tool_choice)
        if mode is None:
            raise BadRequest(
                f"Unsupported tool_choice {tool_choice!r}; "
                f"expected one of {sorted(_MODE_ALIASES)} or a dict naming a tool."
            )
        return NormalizedToolChoice(mode=mode)

    if isinstance(tool_choice, dict):
        kind = tool_choice.get("type")
        if kind in ("function", "tool"):
            name = (tool_choice.get("function") or {}).get("name") or tool_choice.get("name")
            if not name:
                raise BadRequest("tool_choice of type 'function'/'tool' must name a tool.")
            return NormalizedToolChoice(mode="tool", tool=name)
        mode = _MODE_ALIASES.get(kind) if isinstance(kind, str) else None
        if mode is not None:
            return NormalizedToolChoice(mode=mode)
        raise BadRequest(f"Unsupported tool_choice type {kind!r}.")

    raise BadRequest(
        f"tool_choice must be a string, a dict or None, got {type(tool_choice).__name__}."
    )


class LLMProvider(Protocol):
    """All providers expose the same stream_chat shape.

    Note `stream_chat` is a *plain* method returning an async iterator, not an async
    generator function: everything cheap and fallible (translating messages, validating
    `tool_choice`) happens eagerly at call time so a bad request raises at the call site
    instead of on the consumer's first `__anext__`.
    """

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: ToolChoice | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream events for one round of chat completion.

        `tools` is the OpenAI function-calling schema list. Providers that natively support
        tools forward them; Anthropic translates internally.

        `tool_choice` accepts every spelling `normalize_tool_choice` documents; `None` lets
        the model decide. Raises `BadRequest` eagerly on an unsupported value.
        """
        ...  # pragma: no cover
