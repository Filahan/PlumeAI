"""`app.services.ai_fill` — schema assembly, prompt content and the context budget.

Pure: `fill_ai_fields` takes an `LLMProvider`, so a scripted fake is injected directly and
no database or monkeypatching is involved.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import ChatMessage
from app.llm.events import AgentEvent
from app.services import ai_fill

CTX = {"now": "2026-03-04T08:00:00+01:00", "date": "2026-03-04", "timezone": "Europe/Paris"}

GMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "A Gmail search query."},
        "max_results": {"type": "integer"},
    },
    "required": ["query"],
}


class FakeAction:
    name = "gmail_search"
    label = "Search Gmail"
    description = "Search for emails matching a Gmail query string."
    input_schema = GMAIL_SCHEMA


class FakeProvider:
    """Replays one scripted event list per `stream_chat`, recording what it was asked."""

    def __init__(self, script: list[AgentEvent]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: Any = None,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(
            {"model": model, "messages": list(messages), "tools": tools}
        )
        return self._replay()

    async def _replay(self) -> AsyncIterator[AgentEvent]:
        for ev in self.script:
            yield ev


def _script(payload: dict[str, Any], *, inp: int = 11, out: int = 7) -> list[AgentEvent]:
    return [
        {
            "type": "tool_call",
            "id": "c1",
            "tool": ai_fill.FILL_TOOL_NAME,
            "args": json.dumps(payload),
        },
        {"type": "usage", "inputTokens": inp, "outputTokens": out},
    ]


async def _fill(provider: FakeProvider, **overrides: Any):
    kwargs: dict[str, Any] = {
        "provider": provider,
        "model": "gpt-4o-mini",
        "automation_name": "Morning digest",
        "automation_description": "Summarize unread mail from Dana.",
        "step_name": "Find unread emails",
        "action": FakeAction(),
        "fields": {"query": "Unread emails from dana@acme.com since yesterday"},
        "field_schemas": {"query": GMAIL_SCHEMA["properties"]["query"]},
        "prior_outputs": {},
        "ctx": CTX,
    }
    kwargs.update(overrides)
    return await ai_fill.fill_ai_fields(**kwargs)


# --- schema ------------------------------------------------------------------------------


def test_schema_requires_every_field_and_forbids_extras() -> None:
    schema = ai_fill.build_fill_schema(
        {"query": "the search", "max_results": "how many"},
        {
            "query": GMAIL_SCHEMA["properties"]["query"],
            "max_results": GMAIL_SCHEMA["properties"]["max_results"],
        },
    )

    assert schema["type"] == "object"
    assert schema["required"] == ["query", "max_results"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["max_results"]["type"] == "integer"


def test_field_instruction_is_appended_to_the_catalog_description() -> None:
    schema = ai_fill.build_fill_schema(
        {"query": "Unread mail from Dana"}, {"query": GMAIL_SCHEMA["properties"]["query"]}
    )
    description = schema["properties"]["query"]["description"]

    assert "A Gmail search query." in description
    assert "Unread mail from Dana" in description


def test_a_field_the_action_does_not_describe_still_gets_a_property() -> None:
    """A field missing from the catalog must not silently vanish from the payload."""
    schema = ai_fill.build_fill_schema({"mystery": "anything goes"}, {})

    assert schema["properties"]["mystery"] == {"description": "anything goes"}
    assert schema["required"] == ["mystery"]


def test_the_schema_handed_to_the_model_is_the_one_we_built() -> None:
    schema = ai_fill.build_fill_schema({"a": "x", "b": "y"}, {})
    assert list(schema["properties"]) == ["a", "b"]


# --- truncation --------------------------------------------------------------------------


def test_small_outputs_are_rendered_as_verbatim_json() -> None:
    rendered = ai_fill.render_prior_outputs({"step_aaaaa": {"count": 3}})

    assert json.loads(rendered) == {"step_aaaaa": {"count": 3}}


def test_a_huge_step_output_is_capped_and_marked_truncated() -> None:
    big = {"step_aaaaa": {"body": "x" * 20_000}}

    rendered = ai_fill.render_prior_outputs(big, per_step_cap=500)
    parsed = json.loads(rendered)

    # Capped entries come back as a string, so the block stays parseable JSON.
    assert isinstance(parsed["step_aaaaa"], str)
    assert len(parsed["step_aaaaa"]) <= 500
    assert parsed["step_aaaaa"].endswith("…[truncated]")


def test_the_total_budget_shrinks_the_oldest_step_first() -> None:
    """The step a prompt is about is the newest one, so it keeps its detail longest."""
    outputs = {
        "step_old00": {"body": "o" * 3_000},
        "step_new00": {"body": "n" * 3_000},
    }

    rendered = ai_fill.render_prior_outputs(outputs, per_step_cap=4_000, total_cap=3_500)
    parsed = json.loads(rendered)

    assert isinstance(parsed["step_old00"], str)
    assert parsed["step_old00"].endswith("…[truncated]")
    assert parsed["step_new00"] == {"body": "n" * 3_000}
    assert len(rendered) <= 3_800  # the budget plus the keys/braces around it


def test_every_step_survives_the_budget_at_least_in_outline() -> None:
    outputs = {f"step_{i:05d}": {"body": "x" * 5_000} for i in range(10)}

    rendered = ai_fill.render_prior_outputs(outputs, per_step_cap=5_000, total_cap=1_000)
    parsed = json.loads(rendered)

    assert len(parsed) == 10
    assert all(key in parsed for key in outputs)


def test_no_prior_outputs_renders_an_empty_object() -> None:
    assert ai_fill.render_prior_outputs({}) == "{}"


# --- the prompt --------------------------------------------------------------------------


async def test_prompt_carries_the_instruction_the_context_and_todays_date() -> None:
    provider = FakeProvider(_script({"query": "from:dana is:unread after:2026/03/03"}))

    await _fill(provider, prior_outputs={"step_aaaaa": {"count": 3}})

    system, user = provider.calls[0]["messages"]
    assert system.role == "system"
    assert "ONLY the automation context" in system.content

    assert user.role == "user"
    assert "Unread emails from dana@acme.com since yesterday" in user.content
    assert "2026-03-04" in user.content
    assert "Europe/Paris" in user.content
    assert "Morning digest" in user.content
    assert "Summarize unread mail from Dana." in user.content
    # The action the fields belong to, and the outputs available to fill them from.
    assert "gmail_search" in user.content
    assert "Search for emails matching a Gmail query string." in user.content
    assert '"step_aaaaa":{"count":3}' in user.content


async def test_the_fill_tool_is_forced_with_our_schema() -> None:
    provider = FakeProvider(_script({"query": "x"}))

    await _fill(provider)

    tools = provider.calls[0]["tools"]
    assert [t["function"]["name"] for t in tools] == [ai_fill.FILL_TOOL_NAME]
    assert tools[0]["function"]["parameters"]["required"] == ["query"]


async def test_an_unknown_action_is_described_as_such_rather_than_crashing() -> None:
    provider = FakeProvider(_script({"query": "x"}))

    await _fill(provider, action=None, field_schemas={})

    user = provider.calls[0]["messages"][1]
    assert "(unknown action)" in user.content


# --- result ------------------------------------------------------------------------------


async def test_the_models_payload_and_its_token_cost_come_back() -> None:
    provider = FakeProvider(
        _script({"query": "from:dana is:unread"}, inp=42, out=9)
    )

    result = await _fill(provider)

    assert result.data == {"query": "from:dana is:unread"}
    assert result.input_tokens == 42
    assert result.output_tokens == 9


async def test_all_fields_of_a_step_are_filled_by_one_call() -> None:
    provider = FakeProvider(_script({"query": "from:dana", "max_results": 20}))

    result = await _fill(
        provider,
        fields={"query": "unread from Dana", "max_results": "at most twenty"},
        field_schemas={
            "query": GMAIL_SCHEMA["properties"]["query"],
            "max_results": GMAIL_SCHEMA["properties"]["max_results"],
        },
    )

    assert result.data == {"query": "from:dana", "max_results": 20}
    assert len(provider.calls) == 1
