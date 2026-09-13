"""Tool-using agent loop.

Mirrors the Node `streamAgent` semantics: stream a round of completion, collect any
tool_calls, execute them in parallel, feed results back, loop. Bounded at MAX_ITERATIONS
to avoid runaway sessions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import ChatMessage, LLMProvider
from app.llm.events import AgentEvent
from app.tools.base import ToolResult, redact_args
from app.tools.registry import execute_tool

log = structlog.get_logger("app.agent")

MAX_ITERATIONS = 8


@dataclass
class _Round:
    """Aggregated output of a single streaming round."""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


async def _consume_round(
    stream: AsyncIterator[AgentEvent],
    emit: list[AgentEvent],
    round_: _Round,
) -> _Round:
    """Drain a provider stream into `round_`, buffering text events into `emit`.

    Both accumulators are owned by the caller so that whatever arrived before a mid-stream
    failure is still available to it when this raises.
    """
    async for ev in stream:
        kind = ev.get("type")
        if kind == "text":
            round_.text += ev["delta"]
            emit.append(ev)
        elif kind == "usage":
            round_.input_tokens = ev["inputTokens"]
            round_.output_tokens = ev["outputTokens"]
        elif kind == "tool_call":
            round_.tool_calls.append(
                {"id": ev["id"], "name": ev["tool"], "args": ev["args"]}
            )
    return round_


def _exec_tool_call(tc: dict[str, Any], session: AsyncSession) -> Awaitable[ToolResult]:
    return execute_tool(tc["name"], tc["args"], session)


async def stream_agent(
    *,
    provider: LLMProvider,
    model: str,
    messages: list[ChatMessage],
    session: AsyncSession,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run the tool-using loop, yielding events as they happen.

    The caller is responsible for owning `messages` if it cares about the final state —
    we append to it in place (assistant + tool turns) as the loop progresses.
    """
    total_in = 0
    total_out = 0

    for iteration in range(MAX_ITERATIONS):
        emitted: list[AgentEvent] = []
        round_ = _Round()
        stream = provider.stream_chat(model=model, messages=messages, tools=tools)
        try:
            await _consume_round(stream, emitted, round_)
        except Exception:
            # Text is buffered so we can decide on tool calls before forwarding it. If the
            # round dies mid-stream, hand over whatever did arrive (plus the tokens it
            # cost) before letting the error surface — otherwise a partial answer the user
            # already paid for is silently dropped.
            for ev in emitted:
                yield ev
            total_in += round_.input_tokens
            total_out += round_.output_tokens
            if total_in or total_out:
                yield {"type": "usage", "inputTokens": total_in, "outputTokens": total_out}
            raise

        total_in += round_.input_tokens
        total_out += round_.output_tokens

        # Forward text deltas (we buffered them so we could decide tool_calls after).
        for ev in emitted:
            yield ev

        if not round_.tool_calls:
            yield {"type": "final", "text": round_.text}
            yield {"type": "usage", "inputTokens": total_in, "outputTokens": total_out}
            return

        # Persist the assistant turn that requested the tool calls.
        messages.append(
            ChatMessage(
                role="assistant",
                content=round_.text or None,
                tool_calls=[
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    }
                    for tc in round_.tool_calls
                ],
            )
        )

        # Emit tool_call events + execute in parallel.
        for tc in round_.tool_calls:
            yield {
                "type": "tool_call",
                "id": tc["id"],
                "tool": tc["name"],
                "args": redact_args(tc["args"]),
            }
        results = await asyncio.gather(
            *(_exec_tool_call(tc, session) for tc in round_.tool_calls),
            return_exceptions=False,
        )
        for tc, result in zip(round_.tool_calls, results):
            yield {
                "type": "tool_result",
                "id": tc["id"],
                "tool": tc["name"],
                "ok": result.ok,
                "result": result.content,
            }
            messages.append(
                ChatMessage(role="tool", tool_call_id=tc["id"], content=result.content)
            )

    yield {
        "type": "error",
        "message": f"Stopped after {MAX_ITERATIONS} tool rounds without a final answer.",
    }
    yield {"type": "usage", "inputTokens": total_in, "outputTokens": total_out}
