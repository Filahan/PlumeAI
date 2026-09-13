"""OpenAI + OpenRouter provider — both speak the OpenAI chat-completions wire format."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.errors import ProviderError
from app.llm.base import ChatMessage, LLMProvider, ToolChoice, normalize_tool_choice
from app.llm.events import AgentEvent

# Our normalized mode -> OpenAI's `tool_choice`. OpenAI takes the bare strings.
_OPENAI_TOOL_CHOICE = {"auto": "auto", "none": "none", "required": "required"}


def tool_choice_to_openai(
    tool_choice: ToolChoice | None, has_tools: bool
) -> str | dict[str, Any] | None:
    """Any accepted `tool_choice` spelling → OpenAI's `tool_choice`.

    Mirrors `tool_choice_to_anthropic` so both providers accept exactly the same inputs.
    Returns `None` when the field should be omitted (no tools, or no preference).
    """
    choice = normalize_tool_choice(tool_choice)
    if not has_tools or choice is None:
        return None
    if choice.mode == "tool":
        return {"type": "function", "function": {"name": choice.tool}}
    return _OPENAI_TOOL_CHOICE[choice.mode]


def _part_to_openai(p: dict[str, Any]) -> dict[str, Any]:
    """Map one of our normalized parts ({type:'text'|'image', ...}) to OpenAI's shape."""
    if p.get("type") == "image":
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{p['mime']};base64,{p['base64']}", "detail": "auto"},
        }
    return {"type": "text", "text": p.get("text", "")}


def _msg_to_openai(m: ChatMessage) -> dict[str, Any]:
    """Translate our normalized ChatMessage into the OpenAI wire payload."""
    out: dict[str, Any] = {"role": m.role}
    if m.content is not None:
        if isinstance(m.content, list):
            out["content"] = [_part_to_openai(p) for p in m.content]
        else:
            out["content"] = m.content
    if m.tool_calls:
        out["tool_calls"] = m.tool_calls
    if m.tool_call_id is not None:
        out["tool_call_id"] = m.tool_call_id
    return out


def build_request(
    model: str,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoice | None,
) -> dict[str, Any]:
    """Assemble the chat-completions payload. Pure — raises on a bad request eagerly."""
    params: dict[str, Any] = {
        "model": model,
        "messages": [_msg_to_openai(m) for m in messages],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        params["tools"] = tools
    # Only set when expressed — sending `None` explicitly is not the same as omitting it.
    wire_choice = tool_choice_to_openai(tool_choice, has_tools=bool(tools))
    if wire_choice is not None:
        params["tool_choice"] = wire_choice
    return params


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible streaming client. Used for both OpenAI and OpenRouter."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: ToolChoice | None = None,
    ) -> AsyncIterator[AgentEvent]:
        # Build (and therefore validate) the request eagerly so a bad `tool_choice` raises
        # here rather than on the consumer's first `__anext__`.
        return self._stream(build_request(model, messages, tools, tool_choice))

    async def _stream(self, params: dict[str, Any]) -> AsyncIterator[AgentEvent]:
        # Accumulators for tool_calls — OpenAI streams the function name and arguments in
        # multiple chunks; we re-emit a single ToolCallEvent per complete call.
        tool_acc: dict[int, dict[str, str]] = {}

        try:
            stream = await self.client.chat.completions.create(**params)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"OpenAI request failed: {exc}", extra={"reason": "upstream"}
            ) from exc

        async for chunk in stream:
            # Usage chunk (sent at the end of the stream when stream_options.include_usage)
            if chunk.usage is not None:
                yield {
                    "type": "usage",
                    "inputTokens": chunk.usage.prompt_tokens or 0,
                    "outputTokens": chunk.usage.completion_tokens or 0,
                }
                continue

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                yield {"type": "text", "delta": delta.content}

            for tc in delta.tool_calls or []:
                idx = tc.index
                acc = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function and tc.function.name:
                    acc["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    acc["args"] += tc.function.arguments

        # End of stream — flush any tool calls.
        for acc in tool_acc.values():
            if acc["name"]:
                yield {
                    "type": "tool_call",
                    "id": acc["id"],
                    "tool": acc["name"],
                    "args": acc["args"],
                }
