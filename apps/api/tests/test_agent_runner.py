"""Tests for `app.agent.runner.stream_agent` — the tool-using loop.

The runner buffers text for the whole round before forwarding it (it can't know whether a
round is a final answer or a tool request until the stream ends), so the interesting case
is what happens to that buffer when the round dies mid-stream. No network, no DB: the
provider is a scripted fake and no round here reaches tool execution.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agent.runner import stream_agent
from app.errors import ProviderError
from app.llm.base import ChatMessage
from app.llm.events import AgentEvent


class ScriptedProvider:
    """Yields a fixed event list, optionally raising once it is exhausted."""

    def __init__(self, events: list[AgentEvent], raises: BaseException | None = None) -> None:
        self.events = events
        self.raises = raises

    def stream_chat(self, *args: Any, **kwargs: Any) -> AsyncIterator[AgentEvent]:
        return self._replay()

    async def _replay(self) -> AsyncIterator[AgentEvent]:
        for ev in self.events:
            yield ev
        if self.raises is not None:
            raise self.raises


async def _collect(provider: ScriptedProvider) -> list[AgentEvent]:
    seen: list[AgentEvent] = []
    async for ev in stream_agent(
        provider=provider,
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
        session=None,  # type: ignore[arg-type]
        tools=None,
    ):
        seen.append(ev)
    return seen


async def test_text_streamed_before_a_mid_round_error_still_reaches_the_client() -> None:
    provider = ScriptedProvider(
        [{"type": "text", "delta": "half an "}, {"type": "text", "delta": "answer"}],
        raises=ProviderError("Anthropic request failed: connection reset"),
    )

    seen: list[AgentEvent] = []
    with pytest.raises(ProviderError):
        async for ev in stream_agent(
            provider=provider,
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            session=None,  # type: ignore[arg-type]
            tools=None,
        ):
            seen.append(ev)

    assert [ev for ev in seen if ev["type"] == "text"] == [
        {"type": "text", "delta": "half an "},
        {"type": "text", "delta": "answer"},
    ]


async def test_usage_seen_before_a_mid_round_error_is_forwarded() -> None:
    """Tokens were spent even though the round failed — the router records what it sees."""
    provider = ScriptedProvider(
        [
            {"type": "text", "delta": "partial"},
            {"type": "usage", "inputTokens": 12, "outputTokens": 34},
        ],
        raises=ProviderError("truncated", extra={"reason": "max_tokens"}),
    )

    seen: list[AgentEvent] = []
    with pytest.raises(ProviderError):
        async for ev in stream_agent(
            provider=provider,
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            session=None,  # type: ignore[arg-type]
            tools=None,
        ):
            seen.append(ev)

    assert seen == [
        {"type": "text", "delta": "partial"},
        {"type": "usage", "inputTokens": 12, "outputTokens": 34},
    ]


async def test_no_usage_event_means_no_usage_is_invented() -> None:
    provider = ScriptedProvider(
        [{"type": "text", "delta": "partial"}], raises=ProviderError("boom")
    )

    seen: list[AgentEvent] = []
    with pytest.raises(ProviderError):
        async for ev in stream_agent(
            provider=provider,
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            session=None,  # type: ignore[arg-type]
            tools=None,
        ):
            seen.append(ev)

    assert [ev["type"] for ev in seen] == ["text"]


async def test_successful_round_without_tool_calls_emits_final_then_usage() -> None:
    provider = ScriptedProvider(
        [
            {"type": "text", "delta": "all "},
            {"type": "text", "delta": "done"},
            {"type": "usage", "inputTokens": 5, "outputTokens": 7},
        ]
    )

    seen = await _collect(provider)

    assert seen == [
        {"type": "text", "delta": "all "},
        {"type": "text", "delta": "done"},
        {"type": "final", "text": "all done"},
        {"type": "usage", "inputTokens": 5, "outputTokens": 7},
    ]
