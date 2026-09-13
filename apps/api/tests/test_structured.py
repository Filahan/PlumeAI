"""Unit tests for `app.llm.structured` against a scripted fake provider.

The fake provider is injected directly — `complete_json` takes an `LLMProvider`, so no
module attribute needs monkeypatching and no DB session is involved.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.errors import ProviderError, ValidationFailure
from app.llm.base import ChatMessage
from app.llm.events import AgentEvent
from app.llm.structured import StructuredResult, complete_json

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class FakeProvider:
    """Replays one scripted event list per `stream_chat` call, recording the call params.

    Mirrors the real providers' shape: `stream_chat` is a plain method returning an async
    iterator, so a bad request would raise at call time rather than on first iteration.
    """

    def __init__(self, scripts: list[list[AgentEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: Any = None,
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
        return self._replay(script)

    async def _replay(self, script: list[AgentEvent]) -> AsyncIterator[AgentEvent]:
        try:
            for ev in script:
                yield ev
        finally:
            self.closed += 1


class FailingProvider:
    """Raises an upstream `ProviderError` from inside the stream."""

    def __init__(self, exc: ProviderError) -> None:
        self.exc = exc

    def stream_chat(self, *args: Any, **kwargs: Any) -> AsyncIterator[AgentEvent]:
        return self._raise()

    async def _raise(self) -> AsyncIterator[AgentEvent]:
        raise self.exc
        yield  # pragma: no cover — makes this an async generator


def _tool_call(args: str) -> AgentEvent:
    return {"type": "tool_call", "id": "call_1", "tool": "emit", "args": args}


def _usage(inp: int, out: int) -> AgentEvent:
    return {"type": "usage", "inputTokens": inp, "outputTokens": out}


def _q() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="q")]


# --- happy path -------------------------------------------------------------------------


async def test_happy_path_returns_structured_result() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "42"}'), _usage(10, 5)]])

    out = await complete_json(provider, "gpt-4o", _q(), SCHEMA)

    assert out == StructuredResult(data={"answer": "42"}, input_tokens=10, output_tokens=5)
    assert len(provider.calls) == 1


async def test_stream_is_closed_after_each_attempt() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "42"}'), _usage(1, 1)]])
    await complete_json(provider, "m", _q(), SCHEMA)
    assert provider.closed == 1


async def test_tool_and_tool_choice_are_forced() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "ok"}')]])

    await complete_json(
        provider, "claude", _q(), SCHEMA, name="plan", description="Emit the plan."
    )

    call = provider.calls[0]
    assert call["tools"] == [
        {
            "type": "function",
            "function": {"name": "plan", "description": "Emit the plan.", "parameters": SCHEMA},
        }
    ]
    assert call["tool_choice"] == {"type": "function", "function": {"name": "plan"}}


# --- usage accounting -------------------------------------------------------------------


async def test_usage_accumulates_across_retries() -> None:
    provider = FakeProvider(
        [
            [_tool_call("{bad"), _usage(10, 4)],
            [_tool_call('{"answer": "ok"}'), _usage(30, 6)],
        ]
    )

    out = await complete_json(provider, "m", _q(), SCHEMA)

    assert out.data == {"answer": "ok"}
    assert out.input_tokens == 40
    assert out.output_tokens == 10


async def test_usage_defaults_to_zero_when_provider_reports_none() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "ok"}')]])
    out = await complete_json(provider, "m", _q(), SCHEMA)
    assert (out.input_tokens, out.output_tokens) == (0, 0)


# --- retries ----------------------------------------------------------------------------


async def test_invalid_json_then_valid_on_retry() -> None:
    provider = FakeProvider([[_tool_call("{not json")], [_tool_call('{"answer": "42"}')]])

    out = await complete_json(provider, "m", _q(), SCHEMA)

    assert out.data == {"answer": "42"}
    assert len(provider.calls) == 2
    retry_messages = provider.calls[1]["messages"]
    assert retry_messages[-2].role == "assistant"
    assert retry_messages[-2].content == "{not json"
    assert retry_messages[-1].role == "user"
    assert "Your previous output was invalid" in retry_messages[-1].content
    assert "Call the tool again with a valid payload." in retry_messages[-1].content


async def test_schema_violation_then_valid_on_retry() -> None:
    provider = FakeProvider([[_tool_call('{"wrong": 1}')], [_tool_call('{"answer": "good"}')]])

    out = await complete_json(provider, "m", _q(), SCHEMA)

    assert out.data == {"answer": "good"}
    assert len(provider.calls) == 2
    assert "did not match the schema" in provider.calls[1]["messages"][-1].content


async def test_no_tool_call_then_valid_on_retry() -> None:
    provider = FakeProvider(
        [[{"type": "text", "delta": "sorry"}], [_tool_call('{"answer": "ok"}')]]
    )

    out = await complete_json(provider, "m", _q(), SCHEMA)

    assert out.data == {"answer": "ok"}
    assert provider.calls[1]["messages"][-2].content == "(no tool call)"


async def test_empty_string_args_are_echoed_verbatim_not_as_placeholder() -> None:
    """`raw` of "" is a real (bad) answer — it must not be confused with "no tool call"."""
    provider = FakeProvider([[_tool_call("")], [_tool_call('{"answer": "ok"}')]])

    await complete_json(provider, "m", _q(), SCHEMA)

    assert provider.calls[1]["messages"][-2].content == ""


async def test_only_the_first_tool_call_is_read() -> None:
    provider = FakeProvider(
        [[_tool_call('{"answer": "first"}'), _tool_call('{"answer": "second"}')]]
    )
    out = await complete_json(provider, "m", _q(), SCHEMA)
    assert out.data == {"answer": "first"}


# --- failures ---------------------------------------------------------------------------


async def test_exhausted_retries_raises_invalid_output() -> None:
    provider = FakeProvider([[_tool_call("nope")]])

    with pytest.raises(ProviderError) as exc:
        await complete_json(provider, "m", _q(), SCHEMA)

    assert exc.value.extra == {"reason": "invalid_output"}
    assert "2 attempt(s)" in exc.value.detail
    assert len(provider.calls) == 2


async def test_max_retries_zero_makes_a_single_attempt() -> None:
    provider = FakeProvider([[_tool_call('{"wrong": 1}')]])

    with pytest.raises(ProviderError):
        await complete_json(provider, "m", _q(), SCHEMA, max_retries=0)

    assert len(provider.calls) == 1


async def test_upstream_error_propagates_without_retrying() -> None:
    provider = FailingProvider(ProviderError("Anthropic request failed: 401"))

    with pytest.raises(ProviderError) as exc:
        await complete_json(provider, "m", _q(), SCHEMA)

    assert exc.value.extra == {"reason": "upstream"}


async def test_upstream_error_keeps_its_own_reason() -> None:
    provider = FailingProvider(
        ProviderError("truncated", extra={"reason": "max_tokens"})
    )

    with pytest.raises(ProviderError) as exc:
        await complete_json(provider, "m", _q(), SCHEMA)

    assert exc.value.extra == {"reason": "max_tokens"}


async def test_non_object_payload_is_rejected() -> None:
    provider = FakeProvider([[_tool_call("[1, 2]")]])

    with pytest.raises(ProviderError) as exc:
        await complete_json(provider, "m", _q(), SCHEMA, max_retries=0)

    assert "JSON object" in exc.value.detail


# --- schema validation ------------------------------------------------------------------


async def test_invalid_schema_raises_validation_failure_before_any_call() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "ok"}')]])

    with pytest.raises(ValidationFailure) as exc:
        await complete_json(provider, "m", _q(), {"type": "not-a-real-type"})

    assert exc.value.detail.startswith("Invalid output schema:")
    assert provider.calls == []


async def test_valid_schema_passes_the_up_front_check() -> None:
    provider = FakeProvider([[_tool_call('{"answer": "ok"}')]])
    assert (await complete_json(provider, "m", _q(), SCHEMA)).data == {"answer": "ok"}


# --- caller state -----------------------------------------------------------------------


async def test_caller_messages_are_not_mutated() -> None:
    provider = FakeProvider([[_tool_call("bad")], [_tool_call('{"answer": "ok"}')]])

    messages = _q()
    await complete_json(provider, "m", messages, SCHEMA)

    assert len(messages) == 1
