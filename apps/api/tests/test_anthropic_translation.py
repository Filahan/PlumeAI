"""Provider-client tests: OpenAI ↔ Anthropic shape translation and stream handling.

Mostly `app.llm.anthropic_client` (the fiddly side of the translation), plus the
`tool_choice` acceptance and event-sequence parity that both provider clients owe the
agent runner. No network, no DB — the SDK streams are faked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from app.errors import BadRequest, ProviderError
from app.llm.anthropic_client import (
    MAX_TOKENS,
    NO_OUTPUT,
    AnthropicProvider,
    build_request,
    messages_to_anthropic,
    part_to_anthropic,
    split_system,
    tool_calls_to_blocks,
    tool_choice_to_anthropic,
    tool_result_block,
    tools_to_anthropic,
)
from app.llm.base import ChatMessage
from app.llm.openai_client import OpenAICompatProvider, tool_choice_to_openai


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
    assert tool_choice_to_openai(choice, has_tools=True) == choice


def test_tool_choice_omitted_when_caller_expressed_no_preference() -> None:
    """`None` means "provider default" — neither client should invent one."""
    assert tool_choice_to_anthropic(None, has_tools=True) is None
    assert tool_choice_to_openai(None, has_tools=True) is None


def test_tool_choice_is_omitted_without_tools() -> None:
    assert tool_choice_to_anthropic(None, has_tools=False) is None
    assert (
        tool_choice_to_anthropic({"type": "function", "function": {"name": "x"}}, has_tools=False)
        is None
    )
    assert tool_choice_to_openai("required", has_tools=False) is None


@pytest.mark.parametrize(
    ("given", "anthropic_wire", "openai_wire"),
    [
        ("auto", {"type": "auto"}, "auto"),
        # Anthropic has a real `none` wire value (ToolChoiceNoneParam), so tools can stay
        # on the request in both clients.
        ("none", {"type": "none"}, "none"),
        # Anthropic spells "required" as "any".
        ("required", {"type": "any"}, "required"),
        ("any", {"type": "any"}, "required"),
        ({"type": "auto"}, {"type": "auto"}, "auto"),
        ({"type": "tool", "name": "emit"}, {"type": "tool", "name": "emit"},
         {"type": "function", "function": {"name": "emit"}}),
    ],
)
def test_tool_choice_string_and_dict_forms(
    given: Any, anthropic_wire: dict, openai_wire: Any
) -> None:
    assert tool_choice_to_anthropic(given, has_tools=True) == anthropic_wire
    assert tool_choice_to_openai(given, has_tools=True) == openai_wire


@pytest.mark.parametrize("bad", ["always", "AUTO", ["emit"], 7, {"type": "nonsense"}])
def test_tool_choice_rejects_unsupported_values(bad: Any) -> None:
    """Both clients reject the same inputs, as BadRequest (a 400, not a 502)."""
    with pytest.raises(BadRequest):
        tool_choice_to_anthropic(bad, has_tools=True)
    with pytest.raises(BadRequest):
        tool_choice_to_openai(bad, has_tools=True)


def test_tool_choice_naming_a_tool_requires_a_name() -> None:
    with pytest.raises(BadRequest, match="must name a tool"):
        tool_choice_to_anthropic({"type": "function", "function": {}}, has_tools=True)


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
    # No preference was expressed, so the field is omitted (Anthropic already defaults to
    # auto when tools are present).
    assert "tool_choice" not in params
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
    response = httpx.Response(
        401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
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




# --- tool results: empty and multimodal -------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_tool_result_blank_text_becomes_placeholder(blank: str) -> None:
    """Anthropic rejects an empty tool_result, and "returned nothing" is a real outcome."""
    block = tool_result_block(ChatMessage(role="tool", tool_call_id="c", content=blank))
    assert block["content"] == NO_OUTPUT


def test_tool_result_none_content_becomes_placeholder() -> None:
    assert tool_result_block(ChatMessage(role="tool", tool_call_id="c"))["content"] == NO_OUTPUT


def test_tool_result_preserves_meaningful_whitespace() -> None:
    block = tool_result_block(ChatMessage(role="tool", tool_call_id="c", content="  ok  "))
    assert block["content"] == "  ok  "


def test_tool_result_keeps_image_parts() -> None:
    block = tool_result_block(
        ChatMessage(
            role="tool",
            tool_call_id="c",
            content=[
                {"type": "text", "text": "screenshot:"},
                {"type": "image", "mime": "image/png", "base64": "IMG"},
            ],
        )
    )
    assert block["content"] == [
        {"type": "text", "text": "screenshot:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "IMG"}},
    ]


def test_tool_result_image_only_drops_blank_text_block() -> None:
    block = tool_result_block(
        ChatMessage(
            role="tool",
            tool_call_id="c",
            content=[
                {"type": "text", "text": "   "},
                {"type": "image", "mime": "image/png", "base64": "IMG"},
            ],
        )
    )
    assert [b["type"] for b in block["content"]] == ["image"]


def test_tool_result_empty_part_list_becomes_placeholder() -> None:
    assert tool_result_block(
        ChatMessage(role="tool", tool_call_id="c", content=[])
    )["content"] == NO_OUTPUT


# --- request assembly -------------------------------------------------------------------


def test_system_key_is_omitted_when_there_is_no_system_prompt() -> None:
    params = build_request("m", [ChatMessage(role="user", content="hi")], None, None)
    assert "system" not in params
    assert "tools" not in params


def test_bad_tool_choice_raises_eagerly_from_stream_chat() -> None:
    """The generator body must not have to start for a bad request to surface."""
    provider = AnthropicProvider(api_key="test")
    with pytest.raises(BadRequest):
        provider.stream_chat(
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
            tool_choice="whenever",
        )


def test_bad_tool_choice_raises_eagerly_from_openai_stream_chat() -> None:
    provider = OpenAICompatProvider(api_key="test")
    with pytest.raises(BadRequest):
        provider.stream_chat(
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
            tool_choice="whenever",
        )


async def test_tool_choice_string_reaches_the_anthropic_wire() -> None:
    out = await _run_stream(
        [_block_start(0, type="text", text=""), _text_delta(0, "x"), _block_stop(0, type="text")],
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
        tool_choice="required",
    )
    assert out.pop()["tool_choice"] == {"type": "any"}


# --- block types we don't model ---------------------------------------------------------


async def test_thinking_and_unknown_blocks_are_no_ops() -> None:
    events = [
        SimpleNamespace(type="message_start"),
        _block_start(0, type="thinking", thinking=""),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="thinking_delta", thinking="hmm"),
        ),
        SimpleNamespace(type="thinking", thinking="hmm", snapshot="hmm"),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="signature_delta", signature="sig"),
        ),
        _block_stop(0, type="thinking", thinking="hmm"),
        _block_start(1, type="server_tool_use", id="srv_1", name="web_search"),
        _block_stop(1, type="server_tool_use", id="srv_1", name="web_search"),
        _block_start(2, type="text", text=""),
        _text_delta(2, "answer"),
        _block_stop(2, type="text", text="answer"),
        SimpleNamespace(type="message_stop"),
    ]
    out = await _run_stream(events, model="m", messages=[ChatMessage(role="user", content="hi")])
    out.pop()

    # Only the real text survives: no thinking text leaks out, and the server-side tool
    # block does not become a client-executable tool_call.
    assert out == [
        {"type": "text", "delta": "answer"},
        {"type": "usage", "inputTokens": 11, "outputTokens": 22},
    ]


async def test_empty_text_delta_is_skipped() -> None:
    out = await _run_stream(
        [_block_start(0, type="text", text=""), _text_delta(0, ""), _block_stop(0, type="text")],
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
    )
    out.pop()
    assert out == [{"type": "usage", "inputTokens": 11, "outputTokens": 22}]


# --- empty stream -----------------------------------------------------------------------


class _EmptyStream(_FakeStream):
    """A stream that yields nothing — `get_final_message()` would assert if called."""

    async def get_final_message(self) -> SimpleNamespace:
        raise AssertionError("get_final_message() must not be called on an empty stream")


async def test_empty_stream_yields_zero_usage_without_asking_for_a_final_message() -> None:
    provider = AnthropicProvider(api_key="test")
    manager = _EmptyStream([], SimpleNamespace())
    provider.client.messages.stream = lambda **params: manager  # type: ignore[assignment]

    out = [ev async for ev in provider.stream_chat(model="m", messages=[])]

    assert out == [{"type": "usage", "inputTokens": 0, "outputTokens": 0}]


# --- truncation -------------------------------------------------------------------------


async def _run_stream_with_final(events: list[SimpleNamespace], final: SimpleNamespace) -> list:
    provider = AnthropicProvider(api_key="test")
    provider.client.messages.stream = (  # type: ignore[assignment]
        lambda **p: _FakeStream(events, final)
    )
    out = []
    async for ev in provider.stream_chat(model="m", messages=[]):
        out.append(ev)
    return out


async def test_max_tokens_stop_reason_raises_after_yielding_what_streamed() -> None:
    events = [
        _block_start(0, type="tool_use", id="toolu_1", name="emit"),
        _json_delta(0, '{"answer": "half'),
        _block_stop(0, type="tool_use", id="toolu_1", name="emit"),
    ]
    final = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=5, output_tokens=8192), stop_reason="max_tokens"
    )
    provider = AnthropicProvider(api_key="test")
    provider.client.messages.stream = (  # type: ignore[assignment]
        lambda **p: _FakeStream(events, final)
    )

    seen: list[dict] = []
    with pytest.raises(ProviderError) as exc:
        async for ev in provider.stream_chat(model="m", messages=[]):
            seen.append(ev)

    # The truncated tool call and the usage were still delivered before the raise, so the
    # caller can account for the spend and see how far the model got.
    assert [ev["type"] for ev in seen] == ["tool_call", "usage"]
    assert seen[0]["args"] == '{"answer": "half'
    assert exc.value.extra == {"reason": "max_tokens"}
    assert "truncated" in exc.value.detail


async def test_normal_stop_reason_does_not_raise() -> None:
    events = [_block_start(0, type="text", text=""), _text_delta(0, "hi"), _block_stop(0)]
    final = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=1, output_tokens=2), stop_reason="end_turn"
    )
    out = await _run_stream_with_final(events, final)
    assert out[-1] == {"type": "usage", "inputTokens": 1, "outputTokens": 2}


# --- partial delivery + cancellation ----------------------------------------------------


async def test_partial_text_is_delivered_before_a_mid_stream_error() -> None:
    provider = AnthropicProvider(api_key="test")
    final = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    manager = _MidStreamFailure(
        [
            _block_start(0, type="text", text=""),
            _text_delta(0, "half an "),
            _text_delta(0, "answer"),
        ],
        final,
    )
    provider.client.messages.stream = lambda **p: manager  # type: ignore[assignment]

    seen: list[dict] = []
    with pytest.raises(ProviderError) as exc:
        async for ev in provider.stream_chat(model="m", messages=[]):
            seen.append(ev)

    assert seen == [{"type": "text", "delta": "half an "}, {"type": "text", "delta": "answer"}]
    assert exc.value.extra == {"reason": "upstream"}


async def test_breaking_out_of_the_stream_closes_it_without_a_provider_error() -> None:
    """A consumer abandoning the stream throws GeneratorExit — not an upstream failure."""
    provider = AnthropicProvider(api_key="test")
    final = SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    closed: list[bool] = []

    class _TrackingStream(_FakeStream):
        async def __aexit__(self, *exc: object) -> None:
            closed.append(True)

    manager = _TrackingStream(
        [
            _block_start(0, type="text", text=""),
            _text_delta(0, "one"),
            _text_delta(0, "two"),
            _block_stop(0, type="text"),
        ],
        final,
    )
    provider.client.messages.stream = lambda **p: manager  # type: ignore[assignment]

    gen = provider.stream_chat(model="m", messages=[])
    seen = []
    async for ev in gen:
        seen.append(ev)
        break
    await gen.aclose()  # type: ignore[attr-defined]

    assert seen == [{"type": "text", "delta": "one"}]
    assert closed == [True]


# --- cross-provider parity --------------------------------------------------------------


class _FakeOpenAIStream:
    """Async-iterable stand-in for the OpenAI streaming response."""

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for c in self._chunks:
            yield c


def _oa_chunk(
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(usage=usage, choices=[SimpleNamespace(delta=delta)])


def _oa_tool_delta(  # type: ignore[no-untyped-def]
    index: int, id_: str | None, name: str | None, args: str | None
):
    return SimpleNamespace(
        index=index, id=id_, function=SimpleNamespace(name=name, arguments=args)
    )


async def test_both_providers_emit_the_same_event_sequence() -> None:
    """One logical response — two SDK wire formats — one AgentEvent sequence."""
    anthropic_events = [
        SimpleNamespace(type="message_start"),
        _block_start(0, type="text", text=""),
        _text_delta(0, "Looking"),
        _synthetic_text("Looking", "Looking"),
        _text_delta(0, " it up"),
        _block_stop(0, type="text", text="Looking it up"),
        _block_start(1, type="tool_use", id="call_1", name="web_search"),
        _json_delta(1, '{"query":'),
        _json_delta(1, ' "cats"}'),
        _block_stop(1, type="tool_use", id="call_1", name="web_search"),
        SimpleNamespace(type="message_stop"),
    ]
    anthropic_out = await _run_stream(
        anthropic_events,
        model="claude",
        messages=[ChatMessage(role="user", content="find cats")],
        tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}],
    )
    anthropic_out.pop()  # drop the captured-params sentinel

    openai_provider = OpenAICompatProvider(api_key="test")
    chunks = [
        _oa_chunk(content="Looking"),
        _oa_chunk(content=" it up"),
        _oa_chunk(tool_calls=[_oa_tool_delta(0, "call_1", "web_search", '{"query":')]),
        _oa_chunk(tool_calls=[_oa_tool_delta(0, None, None, ' "cats"}')]),
        _oa_chunk(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22)),
    ]

    async def fake_create(**params: object) -> _FakeOpenAIStream:
        return _FakeOpenAIStream(chunks)

    openai_provider.client.chat.completions.create = fake_create  # type: ignore[assignment]
    openai_out = [
        ev
        async for ev in openai_provider.stream_chat(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="find cats")],
            tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}],
        )
    ]

    expected = [
        {"type": "text", "delta": "Looking"},
        {"type": "text", "delta": " it up"},
        {
            "type": "tool_call",
            "id": "call_1",
            "tool": "web_search",
            "args": '{"query": "cats"}',
        },
        {"type": "usage", "inputTokens": 11, "outputTokens": 22},
    ]
    # OpenAI flushes tool calls at end-of-stream, so usage arrives first there; compare as
    # sets of events plus the text ordering, which is what the runner actually relies on.
    assert anthropic_out == expected
    assert sorted(openai_out, key=repr) == sorted(expected, key=repr)
    assert [e for e in openai_out if e["type"] == "text"] == expected[:2]
