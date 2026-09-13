"""How one step of an automation actually runs.

Split out of `app.services.executor` so that module stays about the *run*: its lifecycle,
the retry loop around a step, cancellation and finalization. Everything here is about a
single attempt of a single step and knows nothing about retries — it either returns a
`StepResult` or raises, and the executor decides what that means for the run.

Three step types, three shapes of work:

- **action** — resolve the input map (literals and `{{refs}}` deterministically, `ai`
  fields through one `ai_fill` call), then dispatch through `app.tools.registry`.
- **ai** — run the tool-using agent loop against the step's instructions, streaming text
  and tool activity out as run events, then optionally coerce the answer into the step's
  declared JSON schema.
- **filter** — evaluate the step's rules (or ask the model) and report whether the run
  should continue.

Every failure raises. `StepFailure` marks the ones worth retrying (a tool returned
`ok=False`, the agent gave up); `RefError`, `ValidationFailure` and a non-upstream
`ProviderError` are deterministic and the executor will not retry them.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import stream_agent
from app.llm.base import ChatMessage, LLMProvider
from app.llm.structured import complete_json
from app.schemas.documents import ActionStep, AiStep, AutomationDocument, FilterStep, Step
from app.services import ai_fill, run_events
from app.services.catalog import build_catalog
from app.services.filters import evaluate_rules
from app.services.refs import interpolate, resolve_field
from app.tools.registry import execute_tool, list_available_tool_schemas

log = structlog.get_logger("app.executor.step")

# Trace entries quote tool arguments and results; cap them so one chatty tool call can't
# bloat the `run_steps.trace` JSONB column (and the run detail payload) without bound.
TRACE_VALUE_CHARS = 2_000

# Input keys whose values never reach the database or an event.
_SECRET_HINTS = ("password", "token", "secret", "key")
REDACTED = "***"

JSON_COERCION_PROMPT = (
    "Convert the following answer into the requested JSON payload. Use only what the "
    "answer says — do not add facts of your own.\n\nAnswer:\n"
)

FILTER_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "continue": {
            "type": "boolean",
            "description": "True to let the automation carry on, false to stop it here.",
        },
        "reason": {
            "type": "string",
            "description": "One short sentence explaining the decision.",
        },
    },
    "required": ["continue", "reason"],
    "additionalProperties": False,
}

FILTER_SYSTEM_PROMPT = (
    "You are a gate in an automation. Given the automation's context so far and one "
    "instruction, decide whether the automation should continue past this point. Answer "
    "strictly from the context — when it does not support continuing, stop."
)


class StepFailure(RuntimeError):
    """A step attempt failed for a reason that may well succeed on a retry."""


@dataclass
class Usage:
    """Tokens accumulated across every model call a run makes."""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


@dataclass
class StepContext:
    """Everything one step attempt needs. Rebuilt by the executor for each step."""

    session: AsyncSession
    run_id: str
    document: AutomationDocument
    step: Step
    index: int
    ctx: dict[str, Any]
    outputs: dict[str, Any]
    get_provider: Callable[[], Awaitable[LLMProvider]]
    usage: Usage
    # Appended to in place; the executor persists it onto the `run_steps` row.
    trace: list[dict[str, Any]] = field(default_factory=list)

    @property
    def model(self) -> str:
        return self.document.model.model

    def publish(self, type_: str, **payload: Any) -> None:
        run_events.publish(
            self.run_id,
            {"type": type_, "stepId": self.step.id, "index": self.index, **payload},
        )


@dataclass
class StepResult:
    """What a successful step attempt produced."""

    output: Any
    # A `filter` step that decided the run should end sets this; nothing else does.
    stop: bool = False


# ─── helpers ─────────────────────────────────────────────────────────────────────────


def clip(text: str, limit: int = TRACE_VALUE_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def redact(resolved: dict[str, Any]) -> dict[str, Any]:
    """Mask values whose key name suggests a credential before they are persisted."""
    return {
        name: REDACTED if any(hint in name.lower() for hint in _SECRET_HINTS) else value
        for name, value in resolved.items()
    }


def preview(value: Any) -> str:
    """A short, always-safe rendering of a step output for an SSE event."""
    if isinstance(value, str):
        return clip(value)
    return clip(json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str))


def _parse_tool_content(content: str) -> Any:
    """A tool's textual result as structured data when it is JSON, else `{"text": ...}`."""
    try:
        parsed = json.loads(content)
    except ValueError:
        return {"text": content}
    return parsed if isinstance(parsed, (dict, list)) else {"text": content}


def _context_block(sctx: StepContext) -> str:
    doc = sctx.document
    lines = [f"Automation: {doc.name}"]
    if doc.description:
        lines.append(f"What it does: {doc.description}")
    lines.extend(
        [
            f"Today is {sctx.ctx.get('date')} ({sctx.ctx.get('timezone')}); the current "
            f"time is {sctx.ctx.get('now')}.",
            "",
            "Outputs of the steps that already ran, keyed by step id:",
            ai_fill.render_prior_outputs(sctx.outputs) if sctx.outputs else "{}",
        ]
    )
    return "\n".join(lines)


# ─── action steps ────────────────────────────────────────────────────────────────────


async def resolve_action_input(sctx: StepContext) -> dict[str, Any]:
    """Resolve an action step's whole input map.

    `literal`/`ref` fields resolve deterministically (a bad path raises `RefError`, which
    the executor treats as a permanent failure — retrying a dangling reference can only
    fail again). Every `ai` field is filled by one shared `ai_fill` call, so a step with
    three AI fields costs one model round trip, not three.
    """
    step = sctx.step
    assert isinstance(step, ActionStep)

    resolved: dict[str, Any] = {}
    ai_fields: dict[str, str] = {}
    for name, fv in step.settings.input.items():
        if fv.kind == "ai":
            ai_fields[name] = str(fv.value)
        else:
            resolved[name] = resolve_field(fv, sctx.outputs, sctx.ctx)

    if not ai_fields:
        return resolved

    catalog = await build_catalog(sctx.session)
    action = catalog.find_action(step.settings.action)
    properties = (action.input_schema.get("properties") or {}) if action is not None else {}

    result = await ai_fill.fill_ai_fields(
        provider=await sctx.get_provider(),
        model=sctx.model,
        automation_name=sctx.document.name,
        automation_description=sctx.document.description,
        step_name=step.name,
        action=action,
        fields=ai_fields,
        field_schemas={name: properties.get(name) or {} for name in ai_fields},
        prior_outputs=sctx.outputs,
        ctx=sctx.ctx,
    )
    sctx.usage.add(result.input_tokens, result.output_tokens)
    for name in ai_fields:
        resolved[name] = result.data.get(name)
    return resolved


async def run_action_step(sctx: StepContext, resolved: dict[str, Any]) -> StepResult:
    """Dispatch the step's action through the tool registry."""
    step = sctx.step
    assert isinstance(step, ActionStep)

    raw_args = json.dumps(resolved, default=str)
    result = await execute_tool(step.settings.action, raw_args, sctx.session)
    if not result.ok:
        # `execute_tool` never raises — a failure arrives as `ok=False`, and most of them
        # (a 502 from an API, a rate limit) are exactly what a retry is for.
        raise StepFailure(clip(result.content))

    output = result.data if result.data is not None else _parse_tool_content(result.content)
    return StepResult(output=output)


# ─── ai steps ────────────────────────────────────────────────────────────────────────


async def run_ai_step(sctx: StepContext) -> StepResult:
    """Run the agent loop for an `ai` step, then shape its answer.

    The step's instructions become the user turn (with `{{refs}}` interpolated) and the
    automation context — name, today's date, earlier outputs — the system turn. Tool
    activity and text deltas are published as run events as they happen, and mirrored
    into the step's trace so the run detail view still shows them after the fact.
    """
    step = sctx.step
    assert isinstance(step, AiStep)

    instructions = interpolate(step.settings.instructions, sctx.outputs, sctx.ctx)
    provider = await sctx.get_provider()
    tools = await _step_tools(sctx, step)

    messages = [
        ChatMessage(role="system", content=_context_block(sctx)),
        ChatMessage(role="user", content=instructions),
    ]

    final_text = ""
    agent_error: str | None = None
    async for ev in stream_agent(
        provider=provider,
        model=sctx.model,
        messages=messages,
        session=sctx.session,
        tools=tools,
    ):
        kind = ev.get("type")
        if kind == "text":
            sctx.publish("step_text", delta=ev["delta"])
        elif kind == "tool_call":
            args = clip(str(ev.get("args") or ""))
            sctx.publish("step_tool_call", id=ev["id"], tool=ev["tool"], args=args)
            sctx.trace.append(
                {"kind": "tool_call", "id": ev["id"], "tool": ev["tool"], "args": args}
            )
        elif kind == "tool_result":
            content = clip(str(ev.get("result") or ""))
            sctx.publish(
                "step_tool_result",
                id=ev["id"],
                tool=ev["tool"],
                ok=ev["ok"],
                result=content,
            )
            sctx.trace.append(
                {
                    "kind": "tool_result",
                    "id": ev["id"],
                    "tool": ev["tool"],
                    "ok": ev["ok"],
                    "result": content,
                }
            )
        elif kind == "final":
            final_text = ev.get("text") or ""
        elif kind == "usage":
            # `stream_agent` emits one cumulative usage event at the end of the loop.
            sctx.usage.add(ev["inputTokens"], ev["outputTokens"])
        elif kind == "error":
            # Recorded rather than raised on the spot: the runner still has a usage event
            # to emit, and those tokens were spent whether or not the step succeeded.
            agent_error = ev.get("message") or "The agent stopped without an answer."

    if agent_error is not None:
        raise StepFailure(agent_error)

    if step.settings.output.mode != "json":
        return StepResult(output={"text": final_text})

    coerced = await complete_json(
        provider,
        sctx.model,
        [
            ChatMessage(role="system", content=_context_block(sctx)),
            ChatMessage(role="user", content=JSON_COERCION_PROMPT + final_text),
        ],
        step.settings.output.schema_ or {"type": "object"},
        name="emit_output",
        description="Return this step's output in the shape the automation declared.",
    )
    sctx.usage.add(coerced.input_tokens, coerced.output_tokens)
    return StepResult(output=coerced.data)


async def _step_tools(sctx: StepContext, step: AiStep) -> list[dict[str, Any]] | None:
    """The step's requested tools, intersected with what is actually available.

    A tool the author picked before disconnecting its integration simply isn't offered —
    the step still runs, it just can't use that tool. `None` (rather than `[]`) when
    nothing is left, so the provider is asked for a plain completion.
    """
    wanted = set(step.settings.tools)
    if not wanted:
        return None
    available = await list_available_tool_schemas(sctx.session)
    schemas = [s for s in available if (s.get("function") or {}).get("name") in wanted]
    missing = wanted - {(s.get("function") or {}).get("name") for s in schemas}
    if missing:
        log.info("ai_step_tools_unavailable", step_id=step.id, tools=sorted(missing))
    return schemas or None


# ─── filter steps ────────────────────────────────────────────────────────────────────


async def run_filter_step(sctx: StepContext) -> StepResult:
    """Decide whether the run continues past this step."""
    step = sctx.step
    assert isinstance(step, FilterStep)

    if step.settings.mode == "rules":
        assert step.settings.rules is not None
        passed, reason = evaluate_rules(step.settings.rules, sctx.outputs, sctx.ctx)
    else:
        instruction = interpolate(step.settings.instruction or "", sctx.outputs, sctx.ctx)
        result = await complete_json(
            await sctx.get_provider(),
            sctx.model,
            [
                ChatMessage(role="system", content=FILTER_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=f"{_context_block(sctx)}\n\nDecide: {instruction}",
                ),
            ],
            FILTER_DECISION_SCHEMA,
            name="decide",
            description="Report whether the automation should continue.",
        )
        sctx.usage.add(result.input_tokens, result.output_tokens)
        passed = bool(result.data.get("continue"))
        reason = str(result.data.get("reason") or "")

    return StepResult(output={"continue": passed, "reason": reason}, stop=not passed)


# ─── dispatch ────────────────────────────────────────────────────────────────────────


async def prepare_step(sctx: StepContext) -> dict[str, Any] | None:
    """Work done once per step, *before* the retry loop: resolving an action's inputs.

    Deliberately outside the retries — resolving twice would call `ai_fill` again and could
    hand the action different arguments on the second attempt, which is the last thing a
    half-succeeded side effect needs.
    """
    if isinstance(sctx.step, ActionStep):
        return await resolve_action_input(sctx)
    return None


async def run_step(sctx: StepContext, resolved: dict[str, Any] | None) -> StepResult:
    """Execute one attempt of `sctx.step`."""
    if isinstance(sctx.step, ActionStep):
        return await run_action_step(sctx, resolved or {})
    if isinstance(sctx.step, AiStep):
        return await run_ai_step(sctx)
    if isinstance(sctx.step, FilterStep):
        return await run_filter_step(sctx)
    raise StepFailure(f"Unknown step type: {getattr(sctx.step, 'type', '?')!r}")
