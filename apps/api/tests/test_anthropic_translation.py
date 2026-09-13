"""Unit tests for the OpenAI → Anthropic shape translation in `app.llm.anthropic_client`.

Pure functions only — no network, no DB.
"""

from __future__ import annotations

from types import SimpleNamespace

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
# event shapes the real SDK yields (raw content_block_* events + a final message).


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


def _block_stop(index: int) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_stop", index=index)


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
        _block_start(0, type="text", text=""),
        _text_delta(0, "Looking"),
        _text_delta(0, " it up"),
        _block_stop(0),
        _block_start(1, type="tool_use", id="toolu_1", name="web_search"),
        _json_delta(1, '{"query":'),
        _json_delta(1, ' "cats"}'),
        _block_stop(1),
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
        _block_stop(0),
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
        [_block_start(0, type="text", text=""), _text_delta(0, "hi"), _block_stop(0)],
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
