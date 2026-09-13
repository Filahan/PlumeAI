"""`app.services.executor` — what actually happens when a run executes.

Everything upstream of the executor is real: a persisted automation, a pinned version, the
`run_steps` rows `create_run` laid out, `run_events` and the database. Only the two things
that would reach the outside world are swapped out — the LLM provider (a scripted fake,
injected by replacing `executor.resolve_provider`) and the tool registry (a fake
`execute_tool`/`list_available_tool_schemas` in `step_runner`, which is where the executor
calls them from). Backoff sleeps are patched to no-ops so a retry test is instant.

`tests/integration/conftest.py` stubs `executor.start_run_in_background` for every test in
this package, so the API tests aren't racing real executions. This module wants the real
thing, and imports it by name at module scope — before that stub is installed — rather than
reaching for the (patched) module attribute.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.db.models import Run, RunStep, UsageEntry
from app.errors import Conflict, ProviderError, ValidationFailure
from app.llm.events import AgentEvent
from app.agent import runner as agent_runner
from app.services import automations as svc
from app.services import executor, run_events, step_runner
from app.services import runs as runs_svc
from app.services.executor import start_run_in_background
from app.services.refs import RefError
from app.tools.base import ToolResult
from app.utils import LoopLocal, to_ms

# --- fixtures ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_executor(monkeypatch):
    """No real backoff sleeps, no event topics or tasks inherited from another test."""
    monkeypatch.setattr(executor, "_sleep", _no_sleep)
    run_events._subscribers.clear()
    yield
    for task in list(executor.RUNNING_TASKS.values()):
        task.cancel()
    executor.RUNNING_TASKS.clear()
    run_events._subscribers.clear()


async def _no_sleep(_seconds: float) -> None:
    return None


class FakeProvider:
    """Replays one scripted event list per `stream_chat` call, in order."""

    def __init__(self, scripts: list[list[AgentEvent]] | None = None) -> None:
        self.scripts = scripts or []
        self.calls: list[dict[str, Any]] = []

    def stream_chat(
        self,
        model: str,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: Any = None,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append({"model": model, "messages": list(messages), "tools": tools})
        index = min(len(self.calls) - 1, len(self.scripts) - 1)
        return self._replay(self.scripts[index] if self.scripts else [])

    async def _replay(self, script: list[AgentEvent]) -> AsyncIterator[AgentEvent]:
        for ev in script:
            if isinstance(ev, BaseException):
                raise ev
            yield ev


class FakeRegistry:
    """Stands in for `app.tools.registry`: scripted results, recorded calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results: dict[str, list[Any]] = {}
        self.schemas: list[dict[str, Any]] = []

    def script(self, action: str, *results: Any) -> None:
        self.results[action] = list(results)

    async def execute_tool(self, name: str, raw_args: str, session: Any) -> ToolResult:
        self.calls.append((name, json.loads(raw_args)))
        queue = self.results.get(name) or [ToolResult(ok=True, content="{}", data={})]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return await item()
        return item

    async def list_available_tool_schemas(self, session: Any) -> list[dict[str, Any]]:
        return list(self.schemas)


@pytest.fixture
def registry(monkeypatch) -> FakeRegistry:
    reg = FakeRegistry()
    monkeypatch.setattr(step_runner, "execute_tool", reg.execute_tool)
    monkeypatch.setattr(
        step_runner, "list_available_tool_schemas", reg.list_available_tool_schemas
    )
    # An `ai` step's tool calls go through the agent runner's own import of the registry.
    monkeypatch.setattr(agent_runner, "execute_tool", reg.execute_tool)
    return reg


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    fake = FakeProvider()

    async def _resolve(session: Any, provider_name: str) -> FakeProvider:
        return fake

    monkeypatch.setattr(executor, "resolve_provider", _resolve)
    return fake


@pytest.fixture
def run_automation(session, make_document):
    """Persist a document, run it to completion, and hand back the run and its steps."""

    async def go(steps: list[dict], *, name: str = "Demo"):
        automation = await svc.create_automation(session, document=make_document(name, steps))
        await session.commit()
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run_id = run.id
        await session.commit()
        await executor.execute_run(run_id)
        session.expire_all()
        return await runs_svc.get_run(session, run_id)

    return go


# --- document builders -------------------------------------------------------------------


def action_step(step_id: str, action: str, inputs: dict[str, dict], **extra: Any) -> dict:
    return {
        "id": step_id,
        "name": f"Do {action}",
        "type": "action",
        "settings": {"integration": "builtin", "action": action, "input": inputs},
        **extra,
    }


def ai_text_step(step_id: str, instructions: str = "Say hi", **extra: Any) -> dict:
    return {
        "id": step_id,
        "name": "Think",
        "type": "ai",
        "settings": {"instructions": instructions, "tools": [], "output": {"mode": "text"}},
        **extra,
    }


def filter_rules_step(step_id: str, left: str, op: str, right: Any) -> dict:
    return {
        "id": step_id,
        "name": "Gate",
        "type": "filter",
        "settings": {
            "mode": "rules",
            "rules": {
                "combinator": "and",
                "conditions": [
                    {"left": {"kind": "ref", "value": left}, "op": op,
                     "right": {"kind": "literal", "value": right}}
                ],
            },
        },
    }


def _tool_call(args: str, name: str = "emit") -> AgentEvent:
    return {"type": "tool_call", "id": "c1", "tool": name, "args": args}


def _usage(inp: int, out: int) -> AgentEvent:
    return {"type": "usage", "inputTokens": inp, "outputTokens": out}


def _by_id(steps) -> dict[str, Any]:
    return {s.step_id: s for s in steps}


# --- the happy path ----------------------------------------------------------------------


async def test_outputs_flow_from_one_step_into_the_next(registry, run_automation) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 2}))

    run, steps = await run_automation(
        [
            action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
            action_step(
                "step_bbbbb",
                "http",
                {"body": {"kind": "ref", "value": "{{step_aaaaa.output.count}}"}},
            ),
        ]
    )

    assert run.status == "succeeded"
    assert run.error is None
    assert run.ended_at is not None and run.duration_ms is not None
    assert [s.status for s in steps] == ["succeeded", "succeeded"]
    # The second call saw the first step's resolved output, not the template.
    assert registry.calls[1] == ("http", {"body": 2})
    assert _by_id(steps)["step_bbbbb"].resolved_input == {"body": 2}


async def test_a_tools_text_result_is_parsed_when_it_is_json(registry, run_automation) -> None:
    registry.script("http", ToolResult(ok=True, content='{"ok": true}', data=None))

    _, steps = await run_automation(
        [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    )

    assert steps[0].output == {"ok": True}


async def test_a_tools_plain_text_result_is_wrapped(registry, run_automation) -> None:
    registry.script("http", ToolResult(ok=True, content="hello there", data=None))

    _, steps = await run_automation(
        [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    )

    assert steps[0].output == {"text": "hello there"}


async def test_credential_shaped_inputs_are_redacted_before_they_are_stored(
    registry, run_automation
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={}))

    _, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {
                    "url": {"kind": "literal", "value": "https://api.example.com"},
                    "api_key": {"kind": "literal", "value": "super-secret"},
                },
            )
        ]
    )

    assert steps[0].resolved_input == {"url": "https://api.example.com", "api_key": "***"}
    # The tool itself still received the real value.
    assert registry.calls[0][1]["api_key"] == "super-secret"


# --- AI-filled fields --------------------------------------------------------------------


async def test_an_ai_field_is_filled_by_the_model_and_passed_to_the_action(
    registry, provider, run_automation
) -> None:
    provider.scripts = [[_tool_call('{"url": "https://example.com/feed"}'), _usage(12, 3)]]
    registry.script("http", ToolResult(ok=True, content="{}", data={"status": 200}))

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "ai", "value": "The public feed of example.com"}},
            )
        ]
    )

    assert run.status == "succeeded"
    assert registry.calls[0] == ("http", {"url": "https://example.com/feed"})
    assert steps[0].resolved_input == {"url": "https://example.com/feed"}
    # The fill call's tokens are billed to the run.
    assert (run.input_tokens, run.output_tokens) == (12, 3)
    # The instruction reached the model.
    assert "The public feed of example.com" in provider.calls[0]["messages"][1].content


async def test_the_fill_call_is_not_repeated_when_the_action_is_retried(
    registry, provider, run_automation
) -> None:
    """A retry must call the action with the *same* arguments, not re-imagine them."""
    provider.scripts = [[_tool_call('{"url": "https://example.com"}'), _usage(5, 1)]]
    registry.script(
        "http",
        ToolResult(ok=False, content="503 from upstream"),
        ToolResult(ok=True, content="{}", data={"status": 200}),
    )

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "ai", "value": "example.com"}},
                retry={"max_attempts": 2, "backoff_seconds": 1},
            )
        ]
    )

    assert run.status == "succeeded"
    assert len(provider.calls) == 1
    assert [args["url"] for _, args in registry.calls] == [
        "https://example.com",
        "https://example.com",
    ]


# --- retries -----------------------------------------------------------------------------


async def test_a_failing_tool_is_retried_with_backoff_then_succeeds(
    registry, run_automation
) -> None:
    registry.script(
        "http",
        ToolResult(ok=False, content="502 Bad Gateway"),
        ToolResult(ok=False, content="502 Bad Gateway"),
        ToolResult(ok=True, content="{}", data={"status": 200}),
    )

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "literal", "value": "u"}},
                retry={"max_attempts": 3, "backoff_seconds": 10},
            )
        ]
    )

    assert run.status == "succeeded"
    step = steps[0]
    assert step.status == "succeeded"
    assert step.attempt == 3
    assert step.output == {"status": 200}
    attempts = _attempts(step)
    # Every attempt is traced, the winning one included.
    assert [e["n"] for e in attempts] == [1, 2, 3]
    # Exponential: 10s then 20s, and nothing on the attempt that succeeded.
    assert [e.get("retryInSeconds") for e in attempts] == [10, 20, None]
    assert all("502 Bad Gateway" in e["error"] for e in attempts[:2])
    assert attempts[2]["error"] is None


async def test_backoff_is_capped(registry, run_automation) -> None:
    registry.script(
        "http",
        ToolResult(ok=False, content="boom"),
        ToolResult(ok=True, content="{}", data={}),
    )

    _, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "literal", "value": "u"}},
                retry={"max_attempts": 2, "backoff_seconds": 300},
            )
        ]
    )

    attempts = _attempts(steps[0])
    assert attempts[0]["retryInSeconds"] == executor.MAX_BACKOFF_SECONDS


# --- the attempt trace -------------------------------------------------------------------


def _attempts(step) -> list[dict[str, Any]]:
    """Just the `attempt` entries of a step's trace, in the order they were recorded."""
    return [e for e in step.trace if e["kind"] == "attempt"]


def _assert_bounded(step) -> None:
    """Each attempt is a real interval, inside the step's own span and after the last one."""
    attempts = _attempts(step)
    assert attempts, "the step recorded no attempt at all"
    step_started, step_ended = to_ms(step.started_at), to_ms(step.ended_at)
    previous = step_started
    for entry in attempts:
        assert entry["startedAt"] <= entry["endedAt"]
        assert step_started <= entry["startedAt"]
        assert entry["endedAt"] <= step_ended
        assert previous <= entry["startedAt"]
        previous = entry["endedAt"]


async def test_a_step_that_succeeds_first_try_still_records_its_attempt(
    registry, run_automation
) -> None:
    """Without an entry for the winning attempt the UI cannot time it at all."""
    registry.script("http", ToolResult(ok=True, content="{}", data={"status": 200}))

    _, steps = await run_automation(
        [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    )

    step = steps[0]
    assert step.status == "succeeded"
    attempts = _attempts(step)
    assert len(attempts) == 1
    assert attempts[0]["n"] == 1
    assert attempts[0]["error"] is None
    assert "retryInSeconds" not in attempts[0]
    _assert_bounded(step)


async def test_every_step_kind_records_one_attempt_when_it_succeeds(
    registry, provider, run_automation
) -> None:
    """action, ai and filter all retry through the same loop, so all three trace alike."""
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 3}))
    provider.scripts = [[{"type": "text", "delta": "hi"}, _usage(2, 1)]]

    run, steps = await run_automation(
        [
            action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
            filter_rules_step("step_bbbbb", "{{step_aaaaa.output.count}}", "gt", 0),
            ai_text_step("step_ccccc"),
        ]
    )

    assert run.status == "succeeded"
    for step in steps:
        attempts = _attempts(step)
        assert [e["n"] for e in attempts] == [1], step.step_id
        assert attempts[0]["error"] is None
        _assert_bounded(step)


async def test_two_failures_then_a_success_trace_three_bounded_attempts(
    registry, run_automation
) -> None:
    """The default action policy: 3 attempts, 10s backoff — so 10s then 20s, then clean."""
    registry.script(
        "http",
        ToolResult(ok=False, content="502 Bad Gateway"),
        ToolResult(ok=False, content="502 Bad Gateway"),
        ToolResult(ok=True, content="{}", data={"status": 200}),
    )

    run, steps = await run_automation(
        [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    )

    assert run.status == "succeeded"
    step = steps[0]
    assert step.attempt == 3
    attempts = _attempts(step)
    assert [e["n"] for e in attempts] == [1, 2, 3]
    assert [e.get("retryInSeconds") for e in attempts] == [10, 20, None]
    assert all("502 Bad Gateway" in e["error"] for e in attempts[:2])
    assert attempts[2]["error"] is None
    assert "retryInSeconds" not in attempts[2]
    _assert_bounded(step)


async def test_a_permanently_failing_step_traces_one_attempt_per_try(
    registry, run_automation
) -> None:
    registry.script("http", ToolResult(ok=False, content="permanently down"))

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "literal", "value": "u"}},
                retry={"max_attempts": 3, "backoff_seconds": 10},
            )
        ]
    )

    assert run.status == "failed"
    step = steps[0]
    assert step.status == "failed"
    assert step.attempt == 3
    attempts = _attempts(step)
    assert [e["n"] for e in attempts] == [1, 2, 3]
    assert all("permanently down" in e["error"] for e in attempts)
    # The last one has nowhere to retry to.
    assert [e.get("retryInSeconds") for e in attempts] == [10, 20, None]
    assert "retryInSeconds" not in attempts[2]
    _assert_bounded(step)


async def test_a_step_that_never_succeeds_fails_the_run_and_skips_the_rest(
    registry, run_automation
) -> None:
    registry.script("http", ToolResult(ok=False, content="permanently down"))

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "literal", "value": "u"}},
                retry={"max_attempts": 2, "backoff_seconds": 0},
            ),
            ai_text_step("step_bbbbb"),
        ]
    )

    assert run.status == "failed"
    assert "permanently down" in (run.error or "")
    assert [s.status for s in steps] == ["failed", "skipped"]
    assert steps[0].attempt == 2
    assert "permanently down" in (steps[0].error or "")
    # The last attempt carries no retry, so no `retryInSeconds` on it.
    attempts = _attempts(steps[0])
    assert [e["n"] for e in attempts] == [1, 2]
    assert "retryInSeconds" not in attempts[1]


async def test_a_dangling_reference_fails_the_step_without_retrying(
    registry, run_automation
) -> None:
    """Retrying a reference that doesn't resolve can only fail the same way again."""
    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"body": {"kind": "ref", "value": "{{step_zzzzz.output.nope}}"}},
                retry={"max_attempts": 3, "backoff_seconds": 10},
            )
        ]
    )

    assert run.status == "failed"
    assert "step_zzzzz" in (run.error or "")
    assert steps[0].status == "failed"
    assert steps[0].attempt == 1
    assert registry.calls == []
    attempts = _attempts(steps[0])
    assert len(attempts) == 1
    assert "retryInSeconds" not in attempts[0]


async def test_an_invalid_model_output_is_not_retried(registry, provider, run_automation) -> None:
    """`ProviderError(reason=invalid_output)` is deterministic — one shot, then fail."""
    provider.scripts = [
        [ProviderError("nope", extra={"reason": "invalid_output"})],
    ]

    run, steps = await run_automation(
        [
            ai_text_step("step_aaaaa", retry={"max_attempts": 3, "backoff_seconds": 5}),
        ]
    )

    assert run.status == "failed"
    assert steps[0].attempt == 1
    assert len(provider.calls) == 1


async def test_an_upstream_provider_error_is_retried(registry, provider, run_automation) -> None:
    provider.scripts = [
        [ProviderError("rate limited", extra={"reason": "upstream"})],
        [{"type": "text", "delta": "second time lucky"}, _usage(4, 2)],
    ]

    run, steps = await run_automation(
        [ai_text_step("step_aaaaa", retry={"max_attempts": 2, "backoff_seconds": 1})]
    )

    assert run.status == "succeeded"
    assert steps[0].attempt == 2
    assert steps[0].output == {"text": "second time lucky"}


# --- ai steps ----------------------------------------------------------------------------


async def test_an_ai_step_returns_its_text_and_bills_its_tokens(
    registry, provider, run_automation
) -> None:
    provider.scripts = [[{"type": "text", "delta": "All quiet."}, _usage(30, 9)]]

    run, steps = await run_automation([ai_text_step("step_aaaaa", "Summarize the day")])

    assert steps[0].output == {"text": "All quiet."}
    assert (run.input_tokens, run.output_tokens) == (30, 9)
    # Instructions are the user turn; the automation context is the system turn.
    system, user = provider.calls[0]["messages"]
    assert user.content == "Summarize the day"
    assert "Demo" in system.content


async def test_ai_step_instructions_interpolate_earlier_outputs(
    registry, provider, run_automation
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 7}))
    provider.scripts = [[{"type": "text", "delta": "seven"}, _usage(1, 1)]]

    await run_automation(
        [
            action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
            ai_text_step("step_bbbbb", "There were {{step_aaaaa.output.count}} items."),
        ]
    )

    assert provider.calls[0]["messages"][1].content == "There were 7 items."


async def test_a_json_ai_step_coerces_the_answer_through_the_declared_schema(
    registry, provider, run_automation
) -> None:
    provider.scripts = [
        [{"type": "text", "delta": "Two urgent emails from Dana."}, _usage(20, 5)],
        [_tool_call('{"summary": "Two urgent emails", "urgent": true}'), _usage(8, 4)],
    ]

    run, steps = await run_automation(
        [
            {
                "id": "step_aaaaa",
                "name": "Summarize",
                "type": "ai",
                "settings": {
                    "instructions": "Summarize",
                    "tools": [],
                    "output": {
                        "mode": "json",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "urgent": {"type": "boolean"},
                            },
                            "required": ["summary", "urgent"],
                        },
                    },
                },
            }
        ]
    )

    assert run.status == "succeeded"
    assert steps[0].output == {"summary": "Two urgent emails", "urgent": True}
    # Both round trips are billed.
    assert (run.input_tokens, run.output_tokens) == (28, 9)
    # The coercion prompt quotes the answer it is converting.
    assert "Two urgent emails from Dana." in provider.calls[1]["messages"][1].content


async def test_an_ai_step_only_gets_the_tools_that_are_actually_available(
    registry, provider, run_automation
) -> None:
    registry.schemas = [
        {"type": "function", "function": {"name": "web_search", "parameters": {}}},
        {"type": "function", "function": {"name": "http", "parameters": {}}},
    ]
    provider.scripts = [[{"type": "text", "delta": "done"}, _usage(1, 1)]]

    await run_automation(
        [
            {
                "id": "step_aaaaa",
                "name": "Think",
                "type": "ai",
                # `gmail_get` isn't connected any more; `web_search` is.
                "settings": {
                    "instructions": "Look it up",
                    "tools": ["web_search", "gmail_get"],
                    "output": {"mode": "text"},
                },
            }
        ]
    )

    names = [t["function"]["name"] for t in provider.calls[0]["tools"]]
    assert names == ["web_search"]


async def test_an_ai_step_with_no_tools_asks_for_a_plain_completion(
    registry, provider, run_automation
) -> None:
    provider.scripts = [[{"type": "text", "delta": "done"}, _usage(1, 1)]]

    await run_automation([ai_text_step("step_aaaaa")])

    assert provider.calls[0]["tools"] is None


async def test_ai_step_tool_activity_lands_in_the_trace(
    registry, provider, run_automation
) -> None:
    registry.schemas = [{"type": "function", "function": {"name": "http", "parameters": {}}}]
    registry.script("http", ToolResult(ok=True, content="fetched", data=None))
    provider.scripts = [
        [_tool_call('{"url": "https://example.com"}', name="http"), _usage(6, 2)],
        [{"type": "text", "delta": "I fetched it."}, _usage(4, 1)],
    ]

    _, steps = await run_automation(
        [
            {
                "id": "step_aaaaa",
                "name": "Fetch",
                "type": "ai",
                "settings": {
                    "instructions": "Fetch example.com",
                    "tools": ["http"],
                    "output": {"mode": "text"},
                },
            }
        ]
    )

    kinds = [e["kind"] for e in steps[0].trace]
    # The tool activity in the order it happened, then the attempt that produced it.
    assert kinds == ["tool_call", "tool_result", "attempt"]
    assert steps[0].trace[0]["tool"] == "http"
    assert steps[0].trace[1]["ok"] is True
    assert steps[0].trace[1]["result"] == "fetched"


# --- filters -----------------------------------------------------------------------------


async def test_a_filter_that_passes_lets_the_run_carry_on(registry, run_automation) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 3}))

    run, steps = await run_automation(
        [
            action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
            filter_rules_step("step_bbbbb", "{{step_aaaaa.output.count}}", "gt", 0),
            action_step("step_ccccc", "http", {"url": {"kind": "literal", "value": "v"}}),
        ]
    )

    assert run.status == "succeeded"
    assert run.stopped_by_step_id is None
    assert [s.status for s in steps] == ["succeeded", "succeeded", "succeeded"]
    assert _by_id(steps)["step_bbbbb"].output["continue"] is True


async def test_a_filter_that_stops_skips_the_rest_but_the_run_still_succeeds(
    registry, run_automation
) -> None:
    """A gate deciding "nothing to do today" is the automation working, not failing."""
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 0}))

    run, steps = await run_automation(
        [
            action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
            filter_rules_step("step_bbbbb", "{{step_aaaaa.output.count}}", "gt", 0),
            action_step("step_ccccc", "http", {"url": {"kind": "literal", "value": "v"}}),
            ai_text_step("step_ddddd"),
        ]
    )

    assert run.status == "succeeded"
    assert run.error is None
    assert run.stopped_by_step_id == "step_bbbbb"
    assert [s.status for s in steps] == ["succeeded", "succeeded", "skipped", "skipped"]
    gate = _by_id(steps)["step_bbbbb"]
    assert gate.output["continue"] is False
    assert "count" in gate.output["reason"]
    # The step after the gate never ran.
    assert len(registry.calls) == 1


async def test_an_ai_filter_decides_from_the_model(registry, provider, run_automation) -> None:
    provider.scripts = [
        [_tool_call('{"continue": false, "reason": "Nothing worth sending."}'), _usage(9, 2)]
    ]

    run, steps = await run_automation(
        [
            {
                "id": "step_aaaaa",
                "name": "Worth it?",
                "type": "filter",
                "settings": {"mode": "ai", "instruction": "Continue only if it matters."},
            },
            ai_text_step("step_bbbbb"),
        ]
    )

    assert run.status == "succeeded"
    assert run.stopped_by_step_id == "step_aaaaa"
    assert steps[0].output == {"continue": False, "reason": "Nothing worth sending."}
    assert [s.status for s in steps] == ["succeeded", "skipped"]
    assert (run.input_tokens, run.output_tokens) == (9, 2)
    assert "Continue only if it matters." in provider.calls[0]["messages"][1].content


# --- cancellation ------------------------------------------------------------------------


async def test_cancelling_mid_run_stops_it_and_marks_the_step_cancelled(
    session, make_document, registry, monkeypatch
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hang() -> ToolResult:
        entered.set()
        await release.wait()
        return ToolResult(ok=True, content="{}", data={})

    registry.script("http", hang)

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
                ai_text_step("step_bbbbb"),
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    task = start_run_in_background(run_id)
    await asyncio.wait_for(entered.wait(), timeout=5)

    assert executor.request_cancel(run_id) is True
    await asyncio.wait_for(task, timeout=5)

    session.expire_all()
    finished, steps = await runs_svc.get_run(session, run_id)
    assert finished.status == "cancelled"
    assert finished.error is None
    assert finished.ended_at is not None
    assert [s.status for s in steps] == ["cancelled", "skipped"]
    # The task ended cleanly rather than propagating the cancellation.
    assert not task.cancelled()
    assert run_id not in executor.RUNNING_TASKS
    release.set()


async def test_cancelling_a_run_that_is_not_in_this_process_reports_false() -> None:
    assert executor.request_cancel("nope") is False


# --- events ------------------------------------------------------------------------------


async def test_events_are_published_in_execution_order(
    session, make_document, registry, provider
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"count": 0}))
    provider.scripts = [[{"type": "text", "delta": "hi"}, _usage(1, 1)]]

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
                filter_rules_step("step_bbbbb", "{{step_aaaaa.output.count}}", "gt", 0),
                ai_text_step("step_ccccc"),
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    # Subscribed before the run starts, so nothing is missed.
    queue = run_events.subscribe(run_id)
    await executor.execute_run(run_id)

    seen: list[dict] = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is run_events.SENTINEL:
            seen.append({"type": "SENTINEL"})
            break
        seen.append(item)

    types = [(e["type"], e.get("stepId")) for e in seen]
    assert types == [
        ("run_started", None),
        ("step_started", "step_aaaaa"),
        ("step_finished", "step_aaaaa"),
        ("step_started", "step_bbbbb"),
        ("step_finished", "step_bbbbb"),
        ("step_finished", "step_ccccc"),  # skipped by the gate, never started
        ("run_finished", None),
        ("SENTINEL", None),
    ]
    assert seen[1]["attempt"] == 1
    assert seen[2]["output"] == {"count": 0}
    assert seen[2]["outputPreview"] == '{"count":0}'
    assert seen[-3]["status"] == "skipped"
    assert seen[-2]["status"] == "succeeded"


async def test_retries_and_streamed_text_are_announced(
    session, make_document, registry, provider
) -> None:
    registry.script(
        "http",
        ToolResult(ok=False, content="flaky"),
        ToolResult(ok=True, content="{}", data={}),
    )
    provider.scripts = [
        [{"type": "text", "delta": "one "}, {"type": "text", "delta": "two"}, _usage(1, 1)]
    ]

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step(
                    "step_aaaaa",
                    "http",
                    {"url": {"kind": "literal", "value": "u"}},
                    retry={"max_attempts": 2, "backoff_seconds": 3},
                ),
                ai_text_step("step_bbbbb"),
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    queue = run_events.subscribe(run_id)
    await executor.execute_run(run_id)

    events = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is run_events.SENTINEL:
            break
        events.append(item)

    retries = [e for e in events if e["type"] == "step_retry"]
    assert len(retries) == 1
    assert retries[0] == {
        "type": "step_retry",
        "stepId": "step_aaaaa",
        "index": 0,
        "attempt": 1,
        "error": "flaky",
        "retryInSeconds": 3,
    }
    # Two `step_started` for the retried step, one for the next.
    assert [e["attempt"] for e in events if e["type"] == "step_started"] == [1, 2, 1]
    assert [e["delta"] for e in events if e["type"] == "step_text"] == ["one ", "two"]


async def test_a_huge_output_is_only_previewed_on_the_event(
    session, make_document, registry
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"blob": "x" * 5_000}))

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    queue = run_events.subscribe(run_id)
    await executor.execute_run(run_id)

    finished = [
        e
        for e in iter(lambda: queue.get_nowait(), run_events.SENTINEL)
        if isinstance(e, dict) and e["type"] == "step_finished"
    ]
    assert "output" not in finished[0]
    assert len(finished[0]["outputPreview"]) <= step_runner.TRACE_VALUE_CHARS

    # The database still has the whole thing.
    session.expire_all()
    _, steps = await runs_svc.get_run(session, run_id)
    assert steps[0].output == {"blob": "x" * 5_000}


# --- bookkeeping -------------------------------------------------------------------------


async def test_usage_is_recorded_for_the_whole_run(
    session, make_document, registry, provider
) -> None:
    provider.scripts = [
        [{"type": "text", "delta": "a"}, _usage(10, 2)],
        [{"type": "text", "delta": "b"}, _usage(5, 3)],
    ]
    automation = await svc.create_automation(
        session,
        document=make_document("Demo", [ai_text_step("step_aaaaa"), ai_text_step("step_bbbbb")]),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()
    await executor.execute_run(run_id)
    session.expire_all()

    from app.db.models import UsageEntry

    entries = list(
        (await session.execute(select(UsageEntry).where(UsageEntry.conversation_id == run_id)))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert (entries[0].input_tokens, entries[0].output_tokens) == (15, 5)
    assert entries[0].provider == "openai"
    assert entries[0].model == "gpt-4o-mini"
    assert entries[0].source == "run"

    reloaded, _ = await runs_svc.get_run(session, run_id)
    assert (reloaded.input_tokens, reloaded.output_tokens) == (15, 5)


async def test_a_finished_run_updates_the_automations_last_run(
    session, make_document, registry
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={}))

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()
    await executor.execute_run(run_id)
    session.expire_all()

    refreshed = await svc.get_automation(session, automation_id)
    assert refreshed.last_run_id == run_id
    assert refreshed.last_run_status == "succeeded"


async def test_history_is_pruned_once_the_run_finishes(
    session, make_document, registry, monkeypatch
) -> None:
    monkeypatch.setattr(executor, "RUN_HISTORY_LIMIT", 2)
    registry.script("http", ToolResult(ok=True, content="{}", data={}))

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()

    run_ids = []
    for _ in range(3):
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run_id = run.id
        await session.commit()
        run_ids.append(run_id)
        await executor.execute_run(run_id)
        await session.refresh(automation)

    surviving = set(
        (
            await session.execute(select(Run.id).where(Run.automation_id == automation_id))
        )
        .scalars()
        .all()
    )
    assert surviving == set(run_ids[1:])


async def test_a_run_that_is_no_longer_queued_is_left_alone(
    session, make_document, registry
) -> None:
    """Restart recovery may already have failed it; executing anyway would resurrect it."""
    automation = await svc.create_automation(
        session, document=make_document("Demo", [ai_text_step("step_aaaaa")])
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    run.status = "cancelled"
    await session.commit()

    await executor.execute_run(run_id)
    session.expire_all()

    reloaded, steps = await runs_svc.get_run(session, run_id)
    assert reloaded.status == "cancelled"
    assert [s.status for s in steps] == ["pending"]


async def test_an_unknown_run_id_is_a_no_op() -> None:
    await executor.execute_run("does-not-exist")


async def test_a_run_executes_its_pinned_version_not_the_current_draft(
    session, make_document, registry
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={"v": 1}))

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "pinned"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    # The draft moves on *after* the run was created.
    await svc.save_document(
        session,
        automation,
        make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "edited"}})],
        ),
        created_by="user",
    )
    await session.commit()

    await executor.execute_run(run_id)

    assert registry.calls[0][1]["url"] == "pinned"


# --- run timeout -------------------------------------------------------------------------


async def test_a_run_that_overruns_its_budget_fails(
    session, make_document, registry, monkeypatch
) -> None:
    monkeypatch.setattr(executor, "RUN_TIMEOUT_SECONDS", 0.5)

    async def hang() -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(ok=True, content="{}", data={})

    registry.script("http", hang)

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
                ai_text_step("step_bbbbb"),
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    await executor.execute_run(run_id)
    session.expire_all()

    reloaded, steps = await runs_svc.get_run(session, run_id)
    assert reloaded.status == "failed"
    assert reloaded.error == executor.RUN_TIMEOUT_ERROR
    assert [s.status for s in steps] == ["failed", "skipped"]


async def test_a_step_that_overruns_its_own_timeout_is_retried(
    session, make_document, registry
) -> None:
    calls = {"n": 0}

    async def slow_then_fast() -> ToolResult:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(5)
        return ToolResult(ok=True, content="{}", data={"n": calls["n"]})

    registry.script("http", slow_then_fast)

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step(
                    "step_aaaaa",
                    "http",
                    {"url": {"kind": "literal", "value": "u"}},
                    timeout_seconds=1,
                    retry={"max_attempts": 2, "backoff_seconds": 0},
                )
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    # A 1s step timeout is the document minimum; the fake tool sleeps past it once.
    await executor.execute_run(run_id)
    session.expire_all()

    reloaded, steps = await runs_svc.get_run(session, run_id)
    assert reloaded.status == "succeeded"
    assert steps[0].attempt == 2
    assert steps[0].output == {"n": 2}
    # The attempt that timed out, then the one that made it.
    assert [e["error"] for e in _attempts(steps[0])] == ["Timed out", None]


# --- trigger context ---------------------------------------------------------------------


async def test_the_trigger_context_uses_the_schedules_timezone(
    session, registry, monkeypatch
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={}))
    document = {
        "name": "Tokyo",
        "description": "",
        "model": {"provider": "openai", "model": "gpt-4o-mini"},
        "trigger": {
            "type": "schedule",
            "settings": {"mode": "cron", "cron": "0 8 * * *", "timezone": "Asia/Tokyo"},
        },
        "steps": [
            action_step(
                "step_aaaaa", "http", {"tz": {"kind": "literal", "value": "{{trigger.timezone}}"}}
            )
        ],
    }
    automation = await svc.create_automation(session, document=document)
    automation_id = automation.id
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="schedule")
    run_id = run.id
    await session.commit()

    await executor.execute_run(run_id)

    assert registry.calls[0][1]["tz"] == "Asia/Tokyo"


# --- one active run per automation ------------------------------------------------------


async def test_two_concurrent_create_run_calls_leave_exactly_one_winner(
    session, session_factory, make_document
) -> None:
    """The guard that matters: two transactions that both see "no active run".

    Separate sessions, so neither sees the other's uncommitted insert and the in-process
    lock is deliberately bypassed — all that stands between them is the
    `runs_one_active_per_automation` partial unique index, and it has to turn the loser
    into a clean 409 rather than a 500.
    """
    automation = await svc.create_automation(
        session, document=make_document("Demo", [ai_text_step("step_aaaaa")])
    )
    automation_id = automation.id
    await session.commit()

    async def attempt() -> str:
        async with session_factory() as own:
            mine = await svc.get_automation(own, automation_id)
            try:
                run = await runs_svc.create_run(own, mine, trigger="manual")
            except Conflict:
                return "conflict"
            await own.commit()
            return run.id

    first, second = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    outcomes = [first, second]
    assert not any(isinstance(o, BaseException) for o in outcomes), outcomes
    assert sum(o == "conflict" for o in outcomes) == 1, outcomes

    session.expire_all()
    runs = list(
        (
            await session.execute(select(Run).where(Run.automation_id == automation_id))
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == "queued"


async def test_the_loser_of_the_race_leaves_no_orphaned_steps(
    session, session_factory, make_document
) -> None:
    """The savepoint has to take the loser's `run_steps` rows down with its run."""
    automation = await svc.create_automation(
        session,
        document=make_document("Demo", [ai_text_step("step_aaaaa"), ai_text_step("step_bbbbb")]),
    )
    automation_id = automation.id
    await session.commit()

    winner = await runs_svc.create_run(session, automation, trigger="manual")
    winner_id = winner.id
    await session.commit()

    async with session_factory() as own:
        mine = await svc.get_automation(own, automation_id)
        with pytest.raises(Conflict):
            await runs_svc.create_run(own, mine, trigger="schedule")

    session.expire_all()
    step_run_ids = set(
        (await session.execute(select(RunStep.run_id))).scalars().all()
    )
    assert step_run_ids == {winner_id}


async def test_a_finished_run_does_not_block_the_next_one(
    session, make_document, registry
) -> None:
    """The index is partial, so any number of *finished* runs coexist."""
    registry.script("http", ToolResult(ok=True, content="{}", data={}))
    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()

    for _ in range(3):
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run_id = run.id
        await session.commit()
        await executor.execute_run(run_id)
        await session.refresh(automation)

    total = (
        await session.execute(
            select(sa.func.count()).select_from(Run).where(Run.automation_id == automation_id)
        )
    ).scalar_one()
    assert total == 3


# --- concurrency cap --------------------------------------------------------------------


async def test_runs_over_the_concurrency_cap_wait_in_queued(
    session, session_factory, make_document, registry, monkeypatch
) -> None:
    """A run waiting for a slot must not hold a connection, and must still read `queued`."""
    monkeypatch.setattr(executor, "MAX_CONCURRENT_RUNS", 1)
    monkeypatch.setattr(executor, "_run_slots", LoopLocal(lambda: asyncio.Semaphore(1)))

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hang() -> ToolResult:
        entered.set()
        await release.wait()
        return ToolResult(ok=True, content="{}", data={})

    registry.script("http", hang)

    steps = [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    first = await svc.create_automation(session, document=make_document("One", steps))
    second = await svc.create_automation(session, document=make_document("Two", steps))
    await session.commit()
    run_one = (await runs_svc.create_run(session, first, trigger="manual")).id
    run_two = (await runs_svc.create_run(session, second, trigger="manual")).id
    await session.commit()

    task_one = start_run_in_background(run_one)
    task_two = start_run_in_background(run_two)
    await asyncio.wait_for(entered.wait(), timeout=5)

    # The second run is behind the cap: still `queued`, nothing started.
    async with session_factory() as watcher:
        waiting, waiting_steps = await runs_svc.get_run(watcher, run_two)
        assert waiting.status == "queued"
        assert waiting.started_at is None
        assert [s.status for s in waiting_steps] == ["pending"]

    release.set()
    await asyncio.wait_for(asyncio.gather(task_one, task_two), timeout=10)

    async with session_factory() as watcher:
        for run_id in (run_one, run_two):
            done, _ = await runs_svc.get_run(watcher, run_id)
            assert done.status == "succeeded"


async def test_cancelling_a_run_that_is_still_waiting_for_a_slot_records_it(
    session, make_document, registry, monkeypatch
) -> None:
    monkeypatch.setattr(executor, "_run_slots", LoopLocal(lambda: asyncio.Semaphore(1)))

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hang() -> ToolResult:
        entered.set()
        await release.wait()
        return ToolResult(ok=True, content="{}", data={})

    registry.script("http", hang)
    steps = [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})]
    first = await svc.create_automation(session, document=make_document("One", steps))
    second = await svc.create_automation(session, document=make_document("Two", steps))
    await session.commit()
    run_one = (await runs_svc.create_run(session, first, trigger="manual")).id
    run_two = (await runs_svc.create_run(session, second, trigger="manual")).id
    await session.commit()

    task_one = start_run_in_background(run_one)
    task_two = start_run_in_background(run_two)
    await asyncio.wait_for(entered.wait(), timeout=5)

    assert executor.request_cancel(run_two) is True
    await asyncio.wait_for(task_two, timeout=5)

    session.expire_all()
    cancelled, steps_two = await runs_svc.get_run(session, run_two)
    assert cancelled.status == "cancelled"
    assert cancelled.ended_at is not None
    assert [s.status for s in steps_two] == ["cancelled"]

    release.set()
    await asyncio.wait_for(task_one, timeout=10)


async def test_cancel_all_stops_every_run_in_flight(
    session, make_document, registry
) -> None:
    entered = asyncio.Event()

    async def hang() -> ToolResult:
        entered.set()
        await asyncio.sleep(30)
        return ToolResult(ok=True, content="{}", data={})

    registry.script("http", hang)
    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    await session.commit()
    run_id = (await runs_svc.create_run(session, automation, trigger="manual")).id
    await session.commit()

    task = start_run_in_background(run_id)
    await asyncio.wait_for(entered.wait(), timeout=5)

    await executor.cancel_all(timeout=5)

    assert task.done()
    session.expire_all()
    run, steps = await runs_svc.get_run(session, run_id)
    assert run.status == "cancelled"
    assert [s.status for s in steps] == ["cancelled"]


async def test_cancel_all_with_nothing_running_is_a_no_op() -> None:
    await executor.cancel_all()


# --- permanent failures -----------------------------------------------------------------


async def test_a_tool_that_rejected_the_request_is_not_retried(
    registry, run_automation
) -> None:
    """`retryable=False` means the tool will refuse identically next time."""
    registry.script("http", ToolResult(ok=False, content="Unknown tool: http", retryable=False))

    run, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {"url": {"kind": "literal", "value": "u"}},
                retry={"max_attempts": 3, "backoff_seconds": 10},
            )
        ]
    )

    assert run.status == "failed"
    assert steps[0].attempt == 1
    assert len(registry.calls) == 1
    attempts = _attempts(steps[0])
    assert len(attempts) == 1
    assert "retryInSeconds" not in attempts[0]


async def test_the_real_registry_marks_a_rejected_request_permanent() -> None:
    """The classification the executor depends on, asserted on the real registry."""
    from app.tools.registry import execute_tool as real_execute_tool

    unknown = await real_execute_tool("no_such_tool", "{}", None)
    assert unknown.ok is False
    assert unknown.retryable is False

    # The SSRF guard rejects the URL itself — the same URL fails the same way forever.
    blocked = await real_execute_tool(
        "http", json.dumps({"method": "GET", "url": "http://localhost/secret"}), None
    )
    assert blocked.ok is False
    assert blocked.retryable is False


def test_registry_keeps_upstream_provider_errors_retryable() -> None:
    """A `ProviderError` raised inside a tool (e.g. Google's token endpoint returning a
    5xx during refresh) is an upstream hiccup, not a rejection: another attempt may land."""
    from app.errors import BadRequest, ToolError, ToolNotConfigured
    from app.tools import registry

    assert registry._is_retryable(ProviderError("Google token endpoint: 503")) is True
    assert registry._is_retryable(ToolError("timed out")) is True
    assert registry._is_retryable(ToolError("blocked", extra={"retryable": False})) is False
    assert registry._is_retryable(ToolNotConfigured("gmail")) is False
    assert registry._is_retryable(BadRequest("bad url")) is False


def test_is_retryable_classifies_each_kind_of_failure() -> None:
    from app.errors import BadRequest, NotFound, ToolNotConfigured

    # Deterministic: another attempt fails identically.
    assert executor._is_retryable(RefError("no such step")) is False
    assert executor._is_retryable(ValidationFailure("bad schema")) is False
    assert executor._is_retryable(step_runner.PermanentStepFailure("rejected")) is False
    assert executor._is_retryable(ProviderError("x", extra={"reason": "invalid_output"})) is False
    assert executor._is_retryable(ProviderError("x", extra={"reason": "max_tokens"})) is False
    assert executor._is_retryable(NotFound("no API key for openai")) is False
    assert executor._is_retryable(BadRequest("unknown provider")) is False
    assert executor._is_retryable(ToolNotConfigured("gmail is not connected")) is False

    # Transient: worth another attempt.
    assert executor._is_retryable(ProviderError("x", extra={"reason": "upstream"})) is True
    assert executor._is_retryable(step_runner.StepFailure("502")) is True
    assert executor._is_retryable(TimeoutError()) is True
    assert executor._is_retryable(RuntimeError("boom")) is True


# --- finalization of last resort --------------------------------------------------------


async def test_a_run_whose_own_session_cannot_commit_is_still_finalized(
    session, make_document, registry, monkeypatch
) -> None:
    """A poisoned transaction must not leave a run `running` forever.

    `record_usage` is replaced by one that adds a row violating a NOT NULL constraint, so
    the commit at the end of `finalize` raises exactly the way a real integrity problem
    would. The run's *work* all succeeded, and only its bookkeeping commit failed — so the
    terminal state has to be written through a fresh session. Without that, the row would
    sit `running` and the active-run guard would block this automation forever.
    """
    registry.script("http", ToolResult(ok=True, content="{}", data={"ok": True}))

    async def poison(sess, **_kwargs) -> None:
        sess.add(
            UsageEntry(id="poison", provider=None, model=None, input_tokens=1, output_tokens=1)
        )

    monkeypatch.setattr(executor, "record_usage", poison)

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}}),
                action_step("step_bbbbb", "http", {"url": {"kind": "literal", "value": "v"}}),
            ],
        ),
    )
    automation_id = automation.id
    await session.commit()
    run_id = (await runs_svc.create_run(session, automation, trigger="manual")).id
    await session.commit()

    await executor.execute_run(run_id)

    session.expire_all()
    run, steps = await runs_svc.get_run(session, run_id)
    assert run.status == "succeeded"
    assert run.ended_at is not None
    # Both steps committed as they went, so nothing is left mid-flight.
    assert [s.status for s in steps] == ["succeeded", "succeeded"]
    # The point of all of it: the automation is runnable again.
    refreshed = await svc.get_automation(session, automation_id)
    again = await runs_svc.create_run(session, refreshed, trigger="manual")
    assert again.status == "queued"


async def test_a_failed_run_whose_session_dies_still_skips_its_pending_steps(
    session, make_document, registry, monkeypatch
) -> None:
    """The fallback has to tidy the step rows too, not just the run."""
    registry.script("http", ToolResult(ok=False, content="down", retryable=False))

    async def poison(sess, **_kwargs) -> None:
        sess.add(
            UsageEntry(id="poison2", provider=None, model=None, input_tokens=1, output_tokens=1)
        )

    monkeypatch.setattr(executor, "record_usage", poison)
    # A failing step commits its own `failed` row before finalization, so force a poison
    # that lands while a later step is still `pending`.
    monkeypatch.setattr(executor._Execution, "skip_from", _no_skip)

    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [
                action_step(
                    "step_aaaaa",
                    "http",
                    {"url": {"kind": "literal", "value": "u"}},
                    retry={"max_attempts": 1, "backoff_seconds": 0},
                ),
                action_step("step_bbbbb", "http", {"url": {"kind": "literal", "value": "v"}}),
            ],
        ),
    )
    await session.commit()
    run_id = (await runs_svc.create_run(session, automation, trigger="manual")).id
    await session.commit()

    await executor.execute_run(run_id)

    session.expire_all()
    run, steps = await runs_svc.get_run(session, run_id)
    assert run.status == "failed"
    assert run.ended_at is not None
    assert [s.status for s in steps] == ["failed", "skipped"]


async def _no_skip(self, index: int) -> None:
    """Stand-in for `_Execution.skip_from` that leaves the remaining steps pending."""
    return None


async def test_force_finalize_never_walks_back_a_terminal_run(
    session, make_document, registry
) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={}))
    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    await session.commit()
    run_id = (await runs_svc.create_run(session, automation, trigger="manual")).id
    await session.commit()
    await executor.execute_run(run_id)

    await executor._force_finalize(run_id, "cancelled", "should not apply")

    session.expire_all()
    run, steps = await runs_svc.get_run(session, run_id)
    assert run.status == "succeeded"
    assert run.error is None
    assert [s.status for s in steps] == ["succeeded"]


# --- last run pointer -------------------------------------------------------------------


async def test_an_older_run_finishing_late_does_not_overwrite_the_newer_result(
    session, make_document, registry
) -> None:
    """`last_run_status` reports the *latest* run, whatever order they finish in."""
    registry.script("http", ToolResult(ok=True, content="{}", data={}))
    automation = await svc.create_automation(
        session,
        document=make_document(
            "Demo",
            [action_step("step_aaaaa", "http", {"url": {"kind": "literal", "value": "u"}})],
        ),
    )
    automation_id = automation.id
    await session.commit()

    older = await runs_svc.create_run(session, automation, trigger="manual")
    older_id = older.id
    await session.commit()
    # Finish it out of band so a second run can be queued past the active-run guard.
    older.status = "failed"
    await session.commit()

    newer_id = (await runs_svc.create_run(session, automation, trigger="manual")).id
    await session.commit()
    await executor.execute_run(newer_id)
    await session.refresh(automation)
    assert automation.last_run_id == newer_id

    # Now replay the older run, as a restarted worker might. It must not claim the pointer.
    older.status = "queued"
    older.ended_at = None
    await session.execute(
        sa.update(RunStep).where(RunStep.run_id == older_id).values(status="pending")
    )
    await session.commit()
    await executor.execute_run(older_id)

    await session.refresh(automation)
    refreshed = await svc.get_automation(session, automation_id)
    assert refreshed.last_run_id == newer_id
    assert refreshed.last_run_status == "succeeded"


# --- redaction --------------------------------------------------------------------------


async def test_a_nested_credential_is_redacted_too(registry, run_automation) -> None:
    registry.script("http", ToolResult(ok=True, content="{}", data={}))

    _, steps = await run_automation(
        [
            action_step(
                "step_aaaaa",
                "http",
                {
                    "url": {"kind": "literal", "value": "https://api.example.com"},
                    "headers": {
                        "kind": "literal",
                        "value": {
                            "Accept": "application/json",
                            "Authorization_token": "Bearer hunter2",
                        },
                    },
                },
            )
        ]
    )

    assert steps[0].resolved_input == {
        "url": "https://api.example.com",
        "headers": {"Accept": "application/json", "Authorization_token": "***"},
    }
    # The tool still received the real header.
    assert registry.calls[0][1]["headers"]["Authorization_token"] == "Bearer hunter2"
