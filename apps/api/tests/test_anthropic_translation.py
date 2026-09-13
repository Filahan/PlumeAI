"""Unit tests for the OpenAI → Anthropic shape translation in `app.llm.anthropic_client`.

Pure functions only — no network, no DB.
"""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.errors import ProviderError
from app.llm.anthropic_client import (
    MAX_TOKENS,
    AnthropicProvider,
    messages_to_anthropic,
    part_to_anthropic,
    split_system,
    tool_calls_to_blocks,
    tool_choice_to_anthropic,
    tool_result_block,
    tools_to_anthropic,
)
from app.llm.base import ChatMessage


# --- tool schema conversion -------------------------------------------------------------


def test_tools_to_anthropic_maps_function_schema() -> None:
    params = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    out = tools_to_anthropic(
        [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search.",
                    "parameters": params,
                },
            }
        ]
    )
    assert out == [{"name": "web_search", "description": "Search.", "input_schema": params}]


def test_tools_to_anthropic_handles_none_and_missing_fields() -> None:
    assert tools_to_anthropic(None) == []
    assert tools_to_anthropic([{"type": "function", "function": {"name": "bare"}}]) == [
        {"name": "bare", "description": "", "input_schema": {"type": "object", "properties": {}}}
    ]


# --- tool_choice ------------------------------------------------------------------------


def test_tool_choice_forced_tool() -> None:
    choice = {"type": "function", "function": {"name": "emit"}}
    assert tool_choice_to_anthropic(choice, has_tools=True) == {"type": "tool", "name": "emit"}


def test_tool_choice_defaults_to_auto_when_tools_present() -> None:
    assert tool_choice_to_anthropic(None, has_tools=True) == {"type": "auto"}


def test_tool_choice_is_omitted_without_tools() -> None:
    assert tool_choice_to_anthropic(None, has_tools=False) is None
    assert (
        tool_choice_to_anthropic({"type": "function", "function": {"name": "x"}}, has_tools=False)
        is None
    )


# --- system extraction ------------------------------------------------------------------


def test_split_system_extracts_and_removes_system_turns() -> None:
    system, rest = split_system(
        [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ]
    )
    assert system == "You are helpful."
    assert [m.role for m in rest] == ["user", "assistant"]


def test_split_system_joins_multiple_system_turns() -> None:
    system, rest = split_system(
        [
            ChatMessage(role="system", content="One."),
            ChatMessage(role="system", content="Two."),
            ChatMessage(role="user", content="hi"),
        ]
    )
    assert system == "One.\n\nTwo."
    assert len(rest) == 1


def test_split_system_returns_none_when_absent() -> None:
    system, rest = split_system([ChatMessage(role="user", content="hi")])
    assert system is None
    assert len(rest) == 1


# --- content parts ----------------------------------------------------------------------


def test_part_to_anthropic_image_and_text() -> None:
    assert part_to_anthropic({"type": "image", "mime": "image/png", "base64": "AAA"}) == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
    }
    assert part_to_anthropic({"type": "text", "text": "hey"}) == {"type": "text", "text": "hey"}


def test_multimodal_user_message_keeps_working() -> None:
    out = messages_to_anthropic(
        [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "what is this"},
                    {"type": "image", "mime": "image/jpeg", "base64": "ZZZ"},
                ],
            )
        ]
    )
    assert out == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": "ZZZ"},
                },
            ],
        }
    ]


# --- assistant tool_calls → tool_use ----------------------------------------------------


def _assistant_with_calls(text: str | None = None) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=text,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "cats"}'},
            }
        ],
    )


def test_tool_calls_to_blocks_parses_json_arguments() -> None:
    blocks = tool_calls_to_blocks(_assistant_with_calls())
    assert blocks == [
        {"type": "tool_use", "id": "call_1", "name": "web_search", "input": {"query": "cats"}}
    ]


def test_tool_calls_to_blocks_prepends_text_block() -> None:
    blocks = tool_calls_to_blocks(_assistant_with_calls("Let me look."))
    assert blocks[0] == {"type": "text", "text": "Let me look."}
    assert blocks[1]["type"] == "tool_use"


def test_tool_calls_to_blocks_falls_back_to_empty_input_on_bad_json() -> None:
    m = ChatMessage(
        role="assistant",
        tool_calls=[{"id": "c", "function": {"name": "t", "arguments": "not json"}}],
    )
    assert tool_calls_to_blocks(m) == [
        {"type": "tool_use", "id": "c", "name": "t", "input": {}}
    ]


def test_tool_calls_to_blocks_defaults_missing_arguments_to_empty_object() -> None:
    m = ChatMessage(role="assistant", tool_calls=[{"id": "c", "function": {"name": "t"}}])
    assert tool_calls_to_blocks(m)[0]["input"] == {}


# --- tool results -----------------------------------------------------------------------


def test_tool_result_block_shape() -> None:
    assert tool_result_block(ChatMessage(role="tool", tool_call_id="call_1", content="ok")) == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "ok",
    }


def test_consecutive_tool_results_are_grouped_into_one_user_turn() -> None:
    out = messages_to_anthropic(
        [
            ChatMessage(role="user", content="go"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    {"id": "a", "function": {"name": "t1", "arguments": "{}"}},
                    {"id": "b", "function": {"name": "t2", "arguments": "{}"}},
                ],
            ),
            ChatMessage(role="tool", tool_call_id="a", content="res-a"),
            ChatMessage(role="tool", tool_call_id="b", content="res-b"),
            ChatMessage(role="assistant", content="done"),
        ]
    )
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    assert out[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "res-a"},
            {"type": "tool_result", "tool_use_id": "b", "content": "res-b"},
        ],
    }


def test_trailing_tool_results_are_flushed() -> None:
    out = messages_to_anthropic(
        [
            ChatMessage(role="assistant", tool_calls=[{"id": "a", "function": {"name": "t"}}]),
            ChatMessage(role="tool", tool_call_id="a", content="res"),
        ]
    )
    assert out[-1]["role"] == "user"
    assert out[-1]["content"][0]["tool_use_id"] == "a"


def test_two_tool_rounds_produce_separate_result_turns() -> None:
    out = messages_to_anthropic(
        [
            ChatMessage(role="assistant", tool_calls=[{"id": "a", "function": {"name": "t"}}]),
            ChatMessage(role="tool", tool_call_id="a", content="1"),
            ChatMessage(role="assistant", tool_calls=[{"id": "b", "function": {"name": "t"}}]),
            ChatMessage(role="tool", tool_call_id="b", content="2"),
        ]
    )
    assert [m["role"] for m in out] == ["assistant", "user", "assistant", "user"]
    assert len(out[1]["content"]) == 1
    assert len(out[3]["content"]) == 1


def test_empty_assistant_turn_is_dropped() -> None:
    out = messages_to_anthropic(
        [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content=None)]
    )
    assert out == [{"role": "user", "content": "hi"}]


# --- streaming event handling -----------------------------------------------------------
#
# Exercises `AnthropicProvider.stream_chat` against a fake SDK stream that replays the
# event shapes the real SDK yields. `MessageStream.__stream__` fires each raw event AND a
# synthesized convenience event (`text` after a text_delta, `input_json` after an
# input_json_delta), so the scripts below interleave both to pin that we read only the raw
# ones and never double-count a delta.


class _FakeStream:
    def __init__(self, events: list[SimpleNamespace], final: SimpleNamespace) -> None:
        self._events = events
        self._final = final

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for ev in self._events:
            yield ev

    async def get_final_message(self) -> SimpleNamespace:
        return self._final


def _block_start(index: int, **block: object) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_start", index=index, content_block=SimpleNamespace(**block)
    )


def _text_delta(index: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def _json_delta(index: int, partial: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=SimpleNamespace(type="input_json_delta", partial_json=partial),
    )


def _synthetic_text(text: str, snapshot: str) -> SimpleNamespace:
    """The `TextEvent` the SDK fires alongside every text_delta — must be ignored."""
    return SimpleNamespace(type="text", text=text, snapshot=snapshot)


def _synthetic_input_json(partial: str, snapshot: object) -> SimpleNamespace:
    """The `InputJsonEvent` the SDK fires alongside every input_json_delta — ignored."""
    return SimpleNamespace(type="input_json", partial_json=partial, snapshot=snapshot)


def _block_stop(index: int, **block: object) -> SimpleNamespace:
    """The SDK's `ParsedContentBlockStopEvent` — index plus the accumulated block."""
    return SimpleNamespace(
        type="content_block_stop", index=index, content_block=SimpleNamespace(**block)
    )


async def _run_stream(events: list[SimpleNamespace], **kwargs: object) -> list[dict]:
    provider = AnthropicProvider(api_key="test")
    final = SimpleNamespace(usage=SimpleNamespace(input_tokens=11, output_tokens=22))
    captured: dict = {}

    def fake_stream(**params: object) -> _FakeStream:
        captured.update(params)
        return _FakeStream(events, final)

    provider.client.messages.stream = fake_stream  # type: ignore[assignment]
    out = [ev async for ev in provider.stream_chat(**kwargs)]  # type: ignore[arg-type]
    out.append({"type": "_params", **captured})
    return out


async def test_stream_emits_text_tool_call_and_usage() -> None:
    events = [
        SimpleNamespace(type="message_start"),
        _block_start(0, type="text", text=""),
        _text_delta(0, "Looking"),
        _synthetic_text("Looking", "Looking"),
        _text_delta(0, " it up"),
        _synthetic_text(" it up", "Looking it up"),
        _block_stop(0, type="text", text="Looking it up"),
        _block_start(1, type="tool_use", id="toolu_1", name="web_search"),
        _json_delta(1, '{"query":'),
        _synthetic_input_json('{"query":', {}),
        _json_delta(1, ' "cats"}'),
        _synthetic_input_json(' "cats"}', {"query": "cats"}),
        _block_stop(1, type="tool_use", id="toolu_1", name="web_search"),
        SimpleNamespace(type="message_delta"),
        SimpleNamespace(type="message_stop"),
    ]
    out = await _run_stream(
        events,
        model="claude-sonnet-4-5",
        messages=[ChatMessage(role="user", content="find cats")],
        tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}],
    )
    params = out.pop()

    assert out == [
        {"type": "text", "delta": "Looking"},
        {"type": "text", "delta": " it up"},
        {
            "type": "tool_call",
            "id": "toolu_1",
            "tool": "web_search",
            "args": '{"query": "cats"}',
        },
        {"type": "usage", "inputTokens": 11, "outputTokens": 22},
    ]
    assert params["tool_choice"] == {"type": "auto"}
    assert params["tools"][0]["name"] == "web_search"
    assert params["max_tokens"] == MAX_TOKENS


async def test_stream_empty_tool_input_becomes_empty_object() -> None:
    events = [
        _block_start(0, type="tool_use", id="toolu_x", name="now"),
        _block_stop(0, type="tool_use", id="toolu_x", name="now"),
    ]
    out = await _run_stream(
        events,
        model="m",
        messages=[ChatMessage(role="user", content="time?")],
        tools=[{"type": "function", "function": {"name": "now", "parameters": {}}}],
        tool_choice={"type": "function", "function": {"name": "now"}},
    )
    params = out.pop()
    assert out[0] == {"type": "tool_call", "id": "toolu_x", "tool": "now", "args": "{}"}
    assert params["tool_choice"] == {"type": "tool", "name": "now"}


async def test_stream_without_tools_sends_no_tool_params() -> None:
    out = await _run_stream(
        [
            _block_start(0, type="text", text=""),
            _text_delta(0, "hi"),
            _synthetic_text("hi", "hi"),
            _block_stop(0, type="text", text="hi"),
        ],
        model="m",
        messages=[
            ChatMessage(role="system", content="be terse"),
            ChatMessage(role="user", content="hi"),
        ],
    )
    params = out.pop()
    assert out == [
        {"type": "text", "delta": "hi"},
        {"type": "usage", "inputTokens": 11, "outputTokens": 22},
    ]
    assert "tools" not in params
    assert "tool_choice" not in params
    assert params["system"] == "be terse"
    assert params["messages"] == [{"role": "user", "content": "hi"}]


# --- upstream error surfacing -----------------------------------------------------------


class _FailingStreamManager:
    """Fake manager whose `__aenter__` raises — the real SDK issues the HTTP request there."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __aenter__(self) -> object:
        raise self._exc

    async def __aexit__(self, *exc: object) -> None:
        return None


class _MidStreamFailure(_FakeStream):
    """Yields a couple of events, then blows up mid-iteration (transport drop)."""

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for ev in self._events:
            yield ev
        raise RuntimeError("connection reset")


async def _drain_with_manager(manager: object) -> list[dict]:
    provider = AnthropicProvider(api_key="test")
    provider.client.messages.stream = lambda **params: manager  # type: ignore[assignment]
    return [ev async for ev in provider.stream_chat(model="m", messages=[])]


async def test_api_status_error_on_enter_becomes_provider_error() -> None:
    response = httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    err = anthropic.APIStatusError("invalid x-api-key", response=response, body=None)

    with pytest.raises(ProviderError) as exc:
        await _drain_with_manager(_FailingStreamManager(err))

    assert "Anthropic request failed" in exc.value.detail
    assert "invalid x-api-key" in exc.value.detail


async def test_generic_error_on_enter_becomes_provider_error() -> None:
    with pytest.raises(ProviderError):
        await _drain_with_manager(_FailingStreamManager(RuntimeError("boom")))


async def test_error_mid_stream_becomes_provider_error() -> None:
    final = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    manager = _MidStreamFailure(
        [_block_start(0, type="text", text=""), _text_delta(0, "partial")], final
    )
    with pytest.raises(ProviderError) as exc:
        await _drain_with_manager(manager)
    assert "connection reset" in exc.value.detail


async def test_provider_error_is_not_double_wrapped() -> None:
    original = ProviderError("already normalized")
    with pytest.raises(ProviderError) as exc:
        await _drain_with_manager(_FailingStreamManager(original))
    assert exc.value is original


# --- tool_choice input validation -------------------------------------------------------


@pytest.mark.parametrize("bad", ["auto", ["emit"], 7])
def test_tool_choice_rejects_non_dict(bad: object) -> None:
    with pytest.raises(ValueError, match="must be a dict or None"):
        tool_choice_to_anthropic(bad, has_tools=True)  # type: ignore[arg-type]


def test_tool_choice_none_is_still_accepted() -> None:
    assert tool_choice_to_anthropic(None, has_tools=True) == {"type": "auto"}
