"""Anthropic provider — translates our normalized message shape to Anthropic's Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from app.errors import ProviderError
from app.llm.base import ChatMessage, LLMProvider
from app.llm.events import AgentEvent


def _split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
    """Anthropic's Messages API takes the system prompt as a separate top-level field."""
    system: str | None = None
    rest: list[ChatMessage] = []
    for m in messages:
        if m.role == "system" and system is None:
            system = m.content or ""
        else:
            rest.append(m)
    return system, rest


def _msg_to_anthropic(m: ChatMessage) -> dict[str, Any]:
    return {
        "role": "user" if m.role == "tool" else m.role,
        "content": m.content or "",
    }


class AnthropicProvider:
    """Streaming Anthropic Messages API client.

    Tool-use is not exercised in this phase (Anthropic uses a different tool format from
    OpenAI). The agent runner short-circuits Anthropic when tools are required.
    """

    def __init__(self, api_key: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if tools:
            raise ProviderError("Anthropic provider does not support tool calling in this version.")

        system, rest = _split_system(messages)
        try:
            stream_ctx = self.client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system or "",
                messages=[_msg_to_anthropic(m) for m in rest],
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        async with stream_ctx as stream:
            async for event in stream:
                # Anthropic emits structured events; we only care about text deltas here.
                if getattr(event, "type", "") == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta and getattr(delta, "type", "") == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield {"type": "text", "delta": text}
            final = await stream.get_final_message()
            yield {
                "type": "usage",
                "inputTokens": final.usage.input_tokens,
                "outputTokens": final.usage.output_tokens,
            }
