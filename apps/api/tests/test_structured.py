"""Unit tests for `app.llm.structured.complete_json` against a scripted fake provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.errors import ProviderError
from app.llm import structured
from app.llm.base import ChatMessage
from app.llm.events import AgentEvent

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class FakeProvider:
    """Yields one scripted event list per `stream_chat` call, recording the call params."""

    def __init__(self, scripts: list[list[AgentEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[dict[str, Any]] = []

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(
            {
                "model": model,
                "messages": list(messages),
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        script = self.scripts[min(len(self.calls) - 1, len(self.scripts) - 1)]
        for ev in script:
            yield ev


def _install(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    async def fake_get_provider_for(session: Any, name: str) -> FakeProvider:
        return provider

    monkeypatch.setattr(structured, "get_provider_for", fake_get_provider_for)


def _tool_call(args: str) -> AgentEvent:
    return {"type": "tool_call", "id": "call_1", "tool": "emit", "args": args}


async def test_happy_path_returns_parsed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        [[_tool_call('{"answer": "42"}'), {"type": "usage", "inputTokens": 1, "outputTokens": 2}]]
    )
    _install(monkeypatch, provider)

    out = await structured.complete_json(
        None, "openai", "gpt-4o", [ChatMessage(role="user", content="q")], SCHEMA
    )

    assert out == {"answer": "42"}
    assert len(provider.calls) == 1


async def test_tool_and_tool_choice_are_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call('{"answer": "ok"}')]])
    _install(monkeypatch, provider)

    await structured.complete_json(
        None,
        "anthropic",
        "claude",
        [ChatMessage(role="user", content="q")],
        SCHEMA,
        name="plan",
        description="Emit the plan.",
    )

    call = provider.calls[0]
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "plan",
                "description": "Emit the plan.",
                "parameters": SCHEMA,
            },
        }
    ]
    assert call["tool_choice"] == {"type": "function", "function": {"name": "plan"}}


async def test_stops_at_done_event(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        [
            [
                _tool_call('{"answer": "first"}'),
                {"type": "done", "status": "succeeded"},
                _tool_call('{"answer": "never-read"}'),
            ]
        ]
    )
    _install(monkeypatch, provider)

    out = await structured.complete_json(
        None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA
    )
    assert out == {"answer": "first"}


async def test_invalid_json_then_valid_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call("{not json")], [_tool_call('{"answer": "42"}')]])
    _install(monkeypatch, provider)

    out = await structured.complete_json(
        None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA
    )

    assert out == {"answer": "42"}
    assert len(provider.calls) == 2
    retry_messages = provider.calls[1]["messages"]
    assert retry_messages[-2].role == "assistant"
    assert retry_messages[-2].content == "{not json"
    assert retry_messages[-1].role == "user"
    assert "Your previous output was invalid" in retry_messages[-1].content
    assert "Call the tool again with a valid payload." in retry_messages[-1].content


async def test_schema_violation_then_valid_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        [[_tool_call('{"wrong": 1}')], [_tool_call('{"answer": "good"}')]]
    )
    _install(monkeypatch, provider)

    out = await structured.complete_json(
        None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA
    )

    assert out == {"answer": "good"}
    assert len(provider.calls) == 2


async def test_no_tool_call_then_valid_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        [[{"type": "text", "delta": "sorry"}], [_tool_call('{"answer": "ok"}')]]
    )
    _install(monkeypatch, provider)

    out = await structured.complete_json(
        None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA
    )
    assert out == {"answer": "ok"}
    assert provider.calls[1]["messages"][-2].content == "(no tool call)"


async def test_exhausted_retries_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call("nope")]])
    _install(monkeypatch, provider)

    with pytest.raises(ProviderError) as exc:
        await structured.complete_json(
            None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA
        )

    assert "2 attempt(s)" in exc.value.detail
    assert len(provider.calls) == 2


async def test_max_retries_zero_makes_a_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call('{"wrong": 1}')]])
    _install(monkeypatch, provider)

    with pytest.raises(ProviderError):
        await structured.complete_json(
            None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA, max_retries=0
        )
    assert len(provider.calls) == 1


async def test_caller_messages_are_not_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call("bad")], [_tool_call('{"answer": "ok"}')]])
    _install(monkeypatch, provider)

    messages = [ChatMessage(role="user", content="q")]
    await structured.complete_json(None, "openai", "m", messages, SCHEMA)
    assert len(messages) == 1


async def test_non_object_payload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider([[_tool_call("[1, 2]")]])
    _install(monkeypatch, provider)

    with pytest.raises(ProviderError) as exc:
        await structured.complete_json(
            None, "openai", "m", [ChatMessage(role="user", content="q")], SCHEMA, max_retries=0
        )
    assert "JSON object" in exc.value.detail
