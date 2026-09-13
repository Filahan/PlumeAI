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
from app.llm.base import (
    ChatMessage,
    LLMProvider,
    NormalizedToolChoice,
    ToolChoice,
    normalize_tool_choice,
)
from app.llm.events import AgentEvent

log = structlog.get_logger("app.llm.anthropic")

MAX_TOKENS = 8192

# Anthropic rejects a tool_result with empty content, and an empty result is a real
# outcome (a tool that returns nothing), so give it a visible placeholder.
NO_OUTPUT = "(no output)"

# Our normalized mode -> Anthropic's `tool_choice`. Anthropic spells "required" as "any";
# "none" is a real wire value (ToolChoiceNoneParam), so tools can stay in the request.
_ANTHROPIC_TOOL_CHOICE: dict[str, dict[str, Any]] = {
    "auto": {"type": "auto"},
    "none": {"type": "none"},
    "required": {"type": "any"},
}


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
    """A `role='tool'` turn → one Anthropic `tool_result` block.

    Multimodal results (a tool that returns a screenshot, say) keep their image parts:
    Anthropic accepts a list of text/image blocks as `tool_result` content.
    """
    content: str | list[dict[str, Any]]
    if isinstance(m.content, list):
        blocks = [part_to_anthropic(p) for p in m.content]
        # Drop blank text blocks so an image-only result isn't padded with empty text.
        blocks = [b for b in blocks if b["type"] != "text" or b["text"].strip()]
        content = blocks if blocks else NO_OUTPUT
    else:
        text = m.content or ""
        content = text if text.strip() else NO_OUTPUT
    return {"type": "tool_result", "tool_use_id": m.tool_call_id or "", "content": content}


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
    tool_choice: ToolChoice | NormalizedToolChoice | None, has_tools: bool
) -> dict[str, Any] | None:
    """Any accepted `tool_choice` spelling → Anthropic's `tool_choice`.

    Returns `None` when the field should be omitted: no tools on the table, or no
    preference expressed. Raises `BadRequest` on an unsupported value.
    """
    choice = (
        tool_choice
        if isinstance(tool_choice, NormalizedToolChoice)
        else normalize_tool_choice(tool_choice)
    )
    if not has_tools or choice is None:
        return None
    if choice.mode == "tool":
        return {"type": "tool", "name": choice.tool}
    return _ANTHROPIC_TOOL_CHOICE[choice.mode]


def build_request(
    model: str,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoice | None,
    *,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """Assemble the full Messages API payload. Pure — raises on a bad request eagerly."""
    choice = normalize_tool_choice(tool_choice)
    system, rest = split_system(messages)
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages_to_anthropic(rest),
    }
    # Omit `system` entirely rather than sending an empty string.
    if system:
        params["system"] = system
    anthropic_tools = tools_to_anthropic(tools)
    if anthropic_tools:
        params["tools"] = anthropic_tools
        wire_choice = tool_choice_to_anthropic(choice, has_tools=True)
        if wire_choice is not None:
            params["tool_choice"] = wire_choice
    return params


class AnthropicProvider(LLMProvider):
    """Streaming Anthropic Messages API client, including tool use."""

    def __init__(self, api_key: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)

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
        params = build_request(model, messages, tools, tool_choice)
        return self._stream(params)

    async def _stream(self, params: dict[str, Any]) -> AsyncIterator[AgentEvent]:
        model = params["model"]
        # Anthropic streams tool arguments as `input_json_delta` fragments keyed by the
        # content-block index; accumulate per index and flush on content_block_stop.
        acc: dict[int, dict[str, str]] = {}
        saw_event = False
        final: Any = None

        # `messages.stream()` only builds the manager — the HTTP request (and therefore any
        # 4xx/5xx) happens on `__aenter__`, and transport errors can surface mid-iteration,
        # so the whole exchange has to sit inside the try.
        try:
            async with self.client.messages.stream(**params) as stream:
                async for event in stream:
                    saw_event = True
                    kind = getattr(event, "type", "")

                    # The SDK interleaves synthesized `text` / `input_json` events with the
                    # raw ones below; we read only the raw events so nothing is counted
                    # twice. Block types we don't model (thinking, server_tool_use, …)
                    # simply never enter `acc` and fall through as no-ops.
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

                # `get_final_message()` asserts a message_start was seen, so only ask for it
                # when the stream actually produced something.
                if saw_event:
                    final = await stream.get_final_message()
        except ProviderError:
            raise
        # Deliberately `Exception`, never `BaseException`: a consumer that breaks out of
        # `async for` closes this generator by throwing `GeneratorExit` (and task
        # cancellation arrives as `CancelledError`) at the yield points above. Both are
        # BaseExceptions and must propagate untouched — swallowing them into a ProviderError
        # would turn a normal early exit, or a cancelled request, into a bogus 502.
        except Exception as exc:  # noqa: BLE001
            log.warning("anthropic_stream_failed", model=model, error=str(exc))
            raise ProviderError(
                f"Anthropic request failed: {exc}", extra={"reason": "upstream"}
            ) from exc

        if final is None:
            log.warning("anthropic_empty_stream", model=model)
            yield {"type": "usage", "inputTokens": 0, "outputTokens": 0}
            return

        yield {
            "type": "usage",
            "inputTokens": final.usage.input_tokens or 0,
            "outputTokens": final.usage.output_tokens or 0,
        }

        stop_reason = getattr(final, "stop_reason", None)
        if stop_reason == "max_tokens":
            # Whatever we streamed is truncated — a half-written JSON tool argument would
            # burn a structured-output retry on something the model got right.
            log.warning(
                "anthropic_response_truncated", model=model, max_tokens=params["max_tokens"]
            )
            raise ProviderError(
                f"Anthropic response hit the {params['max_tokens']}-token cap and is truncated.",
                extra={"reason": "max_tokens"},
            )
