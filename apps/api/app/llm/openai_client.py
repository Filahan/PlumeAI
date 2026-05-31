"""OpenAI + OpenRouter provider — both speak the OpenAI chat-completions wire format."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.errors import ProviderError
from app.llm.base import ChatMessage, LLMProvider
from app.llm.events import AgentEvent


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


class OpenAICompatProvider:
    """OpenAI-compatible streaming client. Used for both OpenAI and OpenRouter."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        params: dict[str, Any] = {
            "model": model,
            "messages": [_msg_to_openai(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = tools

        # Accumulators for tool_calls — OpenAI streams the function name and arguments in
        # multiple chunks; we re-emit a single ToolCallEvent per complete call.
        tool_acc: dict[int, dict[str, str]] = {}

        try:
            stream = await self.client.chat.completions.create(**params)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

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
