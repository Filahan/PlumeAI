"""Anthropic provider — translates our normalized message shape to Anthropic's Messages API.

The translation layer is deliberately a set of small, pure module-level functions so the
(fiddly) OpenAI ↔ Anthropic shape mapping can be unit-tested without touching the network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from app.errors import ProviderError
from app.llm.base import ChatMessage, LLMProvider
from app.llm.events import AgentEvent

log = structlog.get_logger("app.llm.anthropic")

MAX_TOKENS = 8192


def _text_of(content: str | list[dict[str, Any]] | None) -> str:
    """Flatten a normalized content value down to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if p.get("type") != "image")


def split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
    """Anthropic's Messages API takes the system prompt as a separate top-level field.

    Every `system` turn is pulled out (Anthropic rejects `role="system"` in `messages`);
    multiple ones are joined with a blank line in the order they appeared.
    """
    systems: list[str] = []
    rest: list[ChatMessage] = []
    for m in messages:
        if m.role == "system":
            text = _text_of(m.content)
            if text:
                systems.append(text)
        else:
            rest.append(m)
    return ("\n\n".join(systems) if systems else None), rest


def part_to_anthropic(p: dict[str, Any]) -> dict[str, Any]:
    """Map one normalized content part ({type:'text'|'image', ...}) to Anthropic's shape."""
    if p.get("type") == "image":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": p["mime"], "data": p["base64"]},
        }
    return {"type": "text", "text": p.get("text", "")}


def tool_calls_to_blocks(m: ChatMessage) -> list[dict[str, Any]]:
    """Assistant turn with `tool_calls` → Anthropic content blocks.

    Our `ChatMessage.tool_calls` carry the OpenAI shape, where `arguments` is a raw JSON
    *string*; Anthropic wants a decoded object in `input`.
    """
    blocks: list[dict[str, Any]] = []
    text = _text_of(m.content)
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in m.tool_calls:
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        if isinstance(raw, dict):
            args: dict[str, Any] = raw
        else:
            try:
                parsed = json.loads(raw or "{}")
            except (TypeError, ValueError):
                log.warning("anthropic_tool_args_unparseable", tool=fn.get("name"))
                parsed = {}
            args = parsed if isinstance(parsed, dict) else {}
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id") or "",
                "name": fn.get("name") or "",
                "input": args,
            }
        )
    return blocks


def tool_result_block(m: ChatMessage) -> dict[str, Any]:
    """A `role='tool'` turn → one Anthropic `tool_result` block."""
    return {
        "type": "tool_result",
        "tool_use_id": m.tool_call_id or "",
        "content": _text_of(m.content),
    }


def messages_to_anthropic(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Translate the non-system part of our history into Anthropic `messages`.

    Anthropic requires every `tool_result` to sit in a single `user` turn that immediately
    follows the assistant `tool_use` turn, so consecutive `role='tool'` messages are
    grouped into one message with a list of blocks.
    """
    out: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def flush_results() -> None:
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        if m.role == "tool":
            pending_results.append(tool_result_block(m))
            continue

        flush_results()

        if m.role == "assistant" and m.tool_calls:
            out.append({"role": "assistant", "content": tool_calls_to_blocks(m)})
            continue

        if isinstance(m.content, list):
            content: str | list[dict[str, Any]] = [part_to_anthropic(p) for p in m.content]
        else:
            content = m.content or ""
        # Anthropic rejects empty turns; a text-less assistant message carries no signal.
        if not content:
            continue
        out.append({"role": m.role, "content": content})

    flush_results()
    return out


def tools_to_anthropic(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """OpenAI function schemas → Anthropic tool definitions."""
    converted: list[dict[str, Any]] = []
    for t in tools or []:
        fn = t.get("function") or {}
        converted.append(
            {
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


def tool_choice_to_anthropic(
    tool_choice: dict[str, Any] | None, has_tools: bool
) -> dict[str, Any] | None:
    """OpenAI `tool_choice` → Anthropic `tool_choice`.

    `{"type": "function", "function": {"name": n}}` forces tool `n`; `None` and any other
    recognized shape fall back to `auto` when tools are on the table, and to nothing when
    they aren't. A `tool_choice` that isn't a dict is a caller bug, not a preference, so it
    raises rather than silently degrading to `auto`.
    """
    if tool_choice is not None and not isinstance(tool_choice, dict):
        raise ValueError(f"tool_choice must be a dict or None, got {type(tool_choice).__name__}")
    if not has_tools:
        return None
    if isinstance(tool_choice, dict):
        name = (tool_choice.get("function") or {}).get("name") or tool_choice.get("name")
        if tool_choice.get("type") in ("function", "tool") and name:
            return {"type": "tool", "name": name}
        if tool_choice.get("type") in ("auto", "any", "none"):
            return {"type": tool_choice["type"]}
    return {"type": "auto"}


class AnthropicProvider:
    """Streaming Anthropic Messages API client, including tool use."""

    def __init__(self, api_key: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        system, rest = split_system(messages)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": system or "",
            "messages": messages_to_anthropic(rest),
        }
        anthropic_tools = tools_to_anthropic(tools)
        if anthropic_tools:
            params["tools"] = anthropic_tools
            choice = tool_choice_to_anthropic(tool_choice, has_tools=True)
            if choice is not None:
                params["tool_choice"] = choice

        # Anthropic streams tool arguments as `input_json_delta` fragments keyed by the
        # content-block index; accumulate per index and flush on content_block_stop.
        acc: dict[int, dict[str, str]] = {}

        # `messages.stream()` only builds the manager — the HTTP request (and therefore any
        # 4xx/5xx) happens on `__aenter__`, and transport errors can surface mid-iteration,
        # so the whole exchange has to sit inside the try.
        try:
            async with self.client.messages.stream(**params) as stream:
                async for event in stream:
                    kind = getattr(event, "type", "")

                    # The SDK interleaves synthesized `text` / `input_json` events with the
                    # raw ones below; we read only the raw events so nothing is counted twice.
                    if kind == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block is not None and getattr(block, "type", "") == "tool_use":
                            acc[event.index] = {
                                "id": getattr(block, "id", "") or "",
                                "name": getattr(block, "name", "") or "",
                                "args": "",
                            }

                    elif kind == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dtype = getattr(delta, "type", "") if delta is not None else ""
                        if dtype == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                yield {"type": "text", "delta": text}
                        elif dtype == "input_json_delta":
                            entry = acc.get(event.index)
                            if entry is not None:
                                entry["args"] += getattr(delta, "partial_json", "") or ""

                    elif kind == "content_block_stop":
                        entry = acc.pop(getattr(event, "index", -1), None)
                        if entry is not None and entry["name"]:
                            yield {
                                "type": "tool_call",
                                "id": entry["id"],
                                "tool": entry["name"],
                                "args": entry["args"] or "{}",
                            }

                final = await stream.get_final_message()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("anthropic_stream_failed", model=model, error=str(exc))
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        yield {
            "type": "usage",
            "inputTokens": final.usage.input_tokens or 0,
            "outputTokens": final.usage.output_tokens or 0,
        }
