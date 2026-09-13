"""The automation builder's assistant: one LLM turn that *edits* the automation.

The assistant never writes prose the client has to interpret. Every turn produces the
same structured reply — a `message` for the user, a list of typed `operations` to apply
to the document, and a `run_test` flag — and this module is what turns that reply into a
new document version, a test run, and a persisted transcript.

Three decisions shape the module:

1. **The operations are the API.** The schema handed to the model is generated from the
   very `Operation` union `app.services.documents.apply_operations` accepts
   (`ASSISTANT_REPLY_SCHEMA`), so the model cannot propose an edit the builder has no
   way to apply. The payload is schema-checked by `app.llm.structured`, re-validated by
   Pydantic here, and then applied through the same `apply_ops` the human builder uses —
   the assistant gets no privileged path into the document.

2. **A rejected operation is a prompt problem, not a user problem.** `apply_ops` refuses
   the whole batch when any operation is malformed (an unknown step id, an out-of-range
   index), and nothing is written. Rather than surfacing that, `chat` feeds the rejection
   back to the model as another turn and lets it fix itself once; only if the second
   attempt is also rejected does the turn come back with `error` set, the document
   untouched, and the failure recorded in the transcript so the *next* turn still sees
   what went wrong.

3. **The prompt is the product.** Everything the model needs to be useful — today's date,
   the current document, the actions it may use, which integrations are *not* connected,
   and why the last run failed — is assembled into the system prompt by `build_context`.
   The formatting is pure (`render_context` and the `format_*` helpers) so it can be
   tested without a database or a provider.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation
from app.errors import AppError, Conflict
from app.llm.base import ChatMessage
from app.llm.structured import complete_json_for
from app.schemas.documents import AutomationDocument, ModelRef, Operation, ValidationIssue
from app.services import automations as automations_svc
from app.services import executor
from app.services import runs as runs_svc
from app.services.catalog import build_catalog
from app.services.documents import dump_document
from app.services.settings import get_settings_for_client, get_timezone
from app.services.usage import record_usage

log = structlog.get_logger("app.assistant")

__all__ = [
    "ASSISTANT_REPLY_SCHEMA",
    "SYSTEM_PROMPT",
    "AssistantResult",
    "FailedStepInfo",
    "LastRunInfo",
    "build_context",
    "chat",
    "clear_history",
    "format_action",
    "format_catalog",
    "format_document",
    "format_last_run",
    "render_context",
]

# The tool the model is forced to call. Its parameters *are* `ASSISTANT_REPLY_SCHEMA`.
REPLY_TOOL_NAME = "propose_changes"
REPLY_TOOL_DESCRIPTION = (
    "Reply to the user and, when they asked for a change, the operations that make it."
)

# How many past transcript entries are replayed to the model. The document itself is in
# the context, so older turns add tokens without adding information.
MAX_HISTORY_MESSAGES = 20
# How many entries are *kept* in the database. Bounded so a long-lived automation's JSONB
# column cannot grow without limit.
MAX_STORED_MESSAGES = 100

# One automatic self-correction attempt after a rejected batch (so two calls at most).
MAX_ATTEMPTS = 2

# Caps on what goes into the prompt.
MAX_DOCUMENT_CHARS = 12_000
MAX_ACTION_DESCRIPTION_CHARS = 200
MAX_FAILURE_DETAIL_CHARS = 800
MAX_ENUM_VALUES = 12

RETRY_INSTRUCTION = (
    "Your operations were rejected and nothing was changed: {error} "
    "Fix them and call the tool again. Keep the same intent; only correct the "
    "operations themselves (step ids must already exist for update/remove/move, new "
    "step ids must be unique, indexes must be within range)."
)

RUN_BUSY_NOTE = "This automation already has a run in progress, so I didn't start a new one."


# ─── the reply schema ────────────────────────────────────────────────────────────────

# The six members of the `Operation` union. Pydantic leaves `op` out of each member's
# `required` (it has a default), which would make the generated `oneOf` ambiguous for a
# payload that omitted it — so `op` is added back as required below. That is the only
# edit made to the generated schema: everything else is exactly the contract
# `apply_operations` enforces, which is the point of generating it rather than writing
# it by hand.
_OPERATION_MEMBERS = (
    "AddStep",
    "UpdateStep",
    "RemoveStep",
    "MoveStep",
    "SetTrigger",
    "SetMeta",
)


def _operation_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    """`(items_schema, defs)` for one `Operation`, with `$defs` split out to be hoisted.

    The generated `$ref`s are all rooted at `#/$defs/...`, so they keep resolving once
    the definitions sit at the top level of `ASSISTANT_REPLY_SCHEMA` instead.
    """
    schema = TypeAdapter(Operation).json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})
    for name in _OPERATION_MEMBERS:
        member = defs.get(name)
        if isinstance(member, dict):
            required = list(member.get("required", ()))
            if "op" not in required:
                member["required"] = ["op", *required]
    return schema, defs


_OPERATION_ITEMS, _OPERATION_DEFS = _operation_schema()

ASSISTANT_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": (
                "What to say to the user: under 120 words, friendly, plain language, in "
                "the user's own language. Never JSON."
            ),
        },
        "operations": {
            "type": "array",
            "description": (
                "The edits to apply to the automation, in order. Empty when the user "
                "only asked a question."
            ),
            "items": _OPERATION_ITEMS,
        },
        "run_test": {
            "type": "boolean",
            "description": (
                "True only when the user asked to run or test the automation now."
            ),
        },
    },
    "required": ["message", "operations", "run_test"],
    "additionalProperties": False,
    "$defs": _OPERATION_DEFS,
}


SYSTEM_PROMPT = """\
You are PlumeAI's automation assistant. You help non-technical people build, fix and \
understand their automations. You do the editing for them: you make the change and then \
say in one or two plain sentences what you did. You never show them JSON.

# How an automation is shaped
An automation is one trigger followed by a LINEAR list of steps — no branches, no loops. \
Steps run top to bottom and each one can use the output of the steps above it. There are \
three step types:
- `action` — runs one catalog action of one integration (search Gmail, post to Slack).
- `ai` — asks a model to do something described in natural language (summarize, draft, \
classify) and returns text or JSON.
- `filter` — stops the run unless a condition holds; every step after it is skipped.

# How you edit
You change the automation ONLY by returning `operations`, applied in order:
- {"op":"add_step","step":{...},"index":2}  — `index` is optional and appends by default
- {"op":"update_step","step_id":"step_k3f9a","patch":{...}}
- {"op":"remove_step","step_id":"step_k3f9a"}
- {"op":"move_step","step_id":"step_k3f9a","index":0}
- {"op":"set_trigger","trigger":{"type":"manual"}} or \
{"op":"set_trigger","trigger":{"type":"schedule","settings":{"mode":"cron",\
"cron":"0 8 * * 1-5","timezone":"Europe/Paris"}}} (or \
{"mode":"interval","every_minutes":30})
- {"op":"set_meta","name":"Morning digest from my boss"}

New step ids are `step_` followed by 5-8 lowercase letters or digits (e.g. `step_k3f9a`) \
and must be unique in the automation. Never change or reuse an existing step's id.

`update_step` merges: each key in `patch` replaces that top-level field of the step, \
except `settings`, which is merged ONE level deep. So to change a single input field of \
an action you must send the WHOLE `input` object, including the fields that stay:
{"op":"update_step","step_id":"step_k3f9a","patch":{"settings":{"input":{
  "query":{"kind":"ai","value":"Unread emails from dana@acme.com since yesterday"},
  "max_results":{"kind":"literal","value":20}}}}}
Otherwise send the smallest patch that does the job (to rename a step, patch only \
`name`). Never put `id` in a patch.

# Step shapes
action:
{"id":"step_k3f9a","name":"Find unread emails from Dana","type":"action",
 "settings":{"integration":"gmail","action":"gmail_search","input":{
   "query":{"kind":"ai","value":"Unread emails from dana@acme.com since yesterday"},
   "max_results":{"kind":"literal","value":20}}}}
ai:
{"id":"step_p2m7c","name":"Summarize the emails","type":"ai",
 "settings":{"instructions":"Emails: {{step_k3f9a.output}}. Write a 5-bullet summary.",
   "tools":[],"output":{"mode":"text"}}}
filter:
{"id":"step_q8d1e","name":"Only continue if there was mail","type":"filter",
 "settings":{"mode":"rules","rules":{"combinator":"and","conditions":[
   {"left":{"kind":"ref","value":"{{step_k3f9a.output.count}}"},"op":"gt",
    "right":{"kind":"literal","value":0}}]}}}
A filter can also judge in words: \
{"mode":"ai","instruction":"Continue only if the email is urgent."}

# Field values: literal, ref, ai
Every input field of an action step is one of exactly three kinds:
- literal — a fixed value: {"kind":"literal","value":"#general"}
- ref — an earlier step's output passed through unchanged: \
{"kind":"ref","value":"{{step_p2m7c.output.summary}}"}
- ai — a plain-language instruction a model turns into the value at run time: \
{"kind":"ai","value":"A one-line subject for the summary above"}

Prefer `ai` whenever the value depends on an earlier step, on today's date, or on \
anything phrased in natural language — that is what makes these automations work for \
people who cannot write expressions. Use `ref` only when an earlier step's output is \
*exactly* the value the field needs, and `literal` for real constants (a channel, a \
recipient, a limit). A ref may only point at a step ABOVE the current one, or at \
`{{trigger...}}`. Filter conditions accept only `literal` and `ref`, never `ai`.

# Rules you must not break
- Use ONLY the integrations and actions listed in the catalog below, spelled exactly as \
they appear. Never invent an action or guess at its input fields.
- If what the user wants needs an integration listed as not connected, do NOT add any \
step that uses it. Say which integration they have to connect on the Tools page, and add \
only the steps that work without it.
- Give every step a short name in plain language (3-6 words), in the user's language.
- If the automation has no name, or is called "New automation" or "Untitled automation", \
include a `set_meta` with a short descriptive name.
- Set `run_test` to true ONLY when the user asks to run or test the automation now.
- If the user asks a question ("why did it fail?", "what does this do?", "did it \
work?"), answer it in `message` and return an EMPTY `operations` list. Never make edits \
they did not ask for.
- `message` stays under 120 words: friendly, concrete, no JSON, no step ids unless the \
user mentioned one, and always in the user's language.

# Before you reply, check all four
1. Did the user ask for a CHANGE, or ask a QUESTION? A question (including "did it \
work?", "is it running?", "why did it fail?") gets `operations: []` — answer it from the \
automation and the last run shown below. If the question assumes something untrue (they \
ask why it failed but the last run succeeded), say what actually happened; still send no \
operations.
2. The automation shown below ALREADY contains every change from earlier turns in this \
conversation. Never re-send an edit that is already in it, and never re-add a step that \
is already there.
3. Send only the operations the user's latest message calls for — nothing else.
4. `run_test` is true only if this latest message asks to run or test it. Describe in \
`message` what you actually did, not what you did earlier."""


# ─── context formatting (pure) ───────────────────────────────────────────────────────


class ActionLike(Protocol):
    """The slice of `app.services.catalog.CatalogAction` the prompt reads."""

    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]


class IntegrationLike(Protocol):
    """The slice of `app.services.catalog.CatalogIntegration` the prompt reads."""

    name: str
    label: str
    connected: bool
    actions: Sequence[ActionLike]


class CatalogLike(Protocol):
    integrations: Sequence[IntegrationLike]
    builtin_actions: Sequence[ActionLike]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def _format_field(name: str, spec: Any, required: bool) -> str:
    """`query (string, one of: a|b, required)` — type, enum, requiredness, nothing else.

    The full JSON Schema of an action's input is deliberately left out of the prompt:
    the model only has to decide *which* fields to set and with what kind of value, and
    the values themselves are schema-checked later (by `validate_document` for literals,
    and at run time for `ai` fields).
    """
    spec = spec if isinstance(spec, dict) else {}
    parts: list[str] = [str(spec.get("type") or "any")]
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        shown = [str(v) for v in enum[:MAX_ENUM_VALUES]]
        if len(enum) > MAX_ENUM_VALUES:
            shown.append("…")
        parts.append("one of: " + "|".join(shown))
    if required:
        parts.append("required")
    return f"{name} ({', '.join(parts)})"


def format_action(action: ActionLike) -> str:
    """One catalog action as a single prompt line."""
    schema = action.input_schema if isinstance(action.input_schema, dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or ())
    fields = [
        _format_field(name, spec, name in required) for name, spec in (properties or {}).items()
    ]
    inputs = "; ".join(fields) if fields else "none"
    label = _one_line(action.label) or action.name
    description = _clip(_one_line(action.description), MAX_ACTION_DESCRIPTION_CHARS)
    return (
        f"- {action.integration}.{action.name} — {label}: "
        f"{description or '(no description)'} — inputs: {inputs}"
    )


def format_catalog(catalog: CatalogLike) -> str:
    """The usable actions, then the integrations the user still has to connect.

    Only *connected* integrations contribute usable actions: an action the user cannot
    run is worse than no action at all, because the model would happily build a whole
    automation around it. The disconnected ones are still named, so the assistant can
    tell the user what to connect instead of silently doing something else.
    """
    lines: list[str] = []
    connected = [i for i in catalog.integrations if i.connected]
    disconnected = [i for i in catalog.integrations if not i.connected]

    lines.append("## Actions you may use")
    if connected:
        for integ in connected:
            lines.append(f"{integ.name} ({_one_line(integ.label) or integ.name}) — connected:")
            if integ.actions:
                lines.extend(format_action(a) for a in integ.actions)
            else:
                lines.append("- (no actions)")
    else:
        lines.append("(no integrations are connected yet)")

    if catalog.builtin_actions:
        lines.append("builtin — always available:")
        lines.extend(format_action(a) for a in catalog.builtin_actions)

    lines.append("")
    lines.append("## Integrations that are NOT connected")
    if disconnected:
        lines.append(
            "These are not connected (the user must connect them in Tools). Do not add "
            "steps that use them — name the integration in your message instead:"
        )
        for integ in disconnected:
            lines.append(
                f"- {integ.name} ({_one_line(integ.label) or integ.name}) — not connected "
                "(user must connect in Tools)"
            )
    else:
        lines.append("(none — every integration is connected)")

    return "\n".join(lines)


def format_document(document: dict[str, Any]) -> str:
    """The current draft, verbatim, as the model will have to patch it."""
    try:
        rendered = json.dumps(document, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover — defensive
        rendered = str(document)
    return _clip(rendered, MAX_DOCUMENT_CHARS)


@dataclass(frozen=True)
class FailedStepInfo:
    step_id: str
    name: str
    error: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class LastRunInfo:
    """Just enough of the most recent run to answer "why did it fail?"."""

    run_id: str
    status: str
    trigger: str = "manual"
    error: str | None = None
    failed_step: FailedStepInfo | None = None


def format_last_run(last_run: LastRunInfo | None) -> str:
    if last_run is None:
        return "This automation has never been run."
    lines = [
        f"Most recent run: {last_run.status} (trigger: {last_run.trigger}, "
        f"id {last_run.run_id})."
    ]
    if last_run.error:
        lines.append(f"Run error: {_one_line(last_run.error)}")
    step = last_run.failed_step
    if step is not None:
        lines.append(
            f'Failing step: "{step.name}" ({step.step_id})'
            + (f" — {_one_line(step.error)}" if step.error else "")
        )
        if step.detail:
            lines.append("What that step recorded:")
            lines.append(_clip(step.detail, MAX_FAILURE_DETAIL_CHARS))
    return "\n".join(lines)


def render_context(
    *,
    document: dict[str, Any],
    catalog: CatalogLike,
    today: str,
    now: str,
    timezone_name: str,
    last_run: LastRunInfo | None,
) -> str:
    """The whole context block, appended to `SYSTEM_PROMPT`. Pure."""
    return "\n".join(
        [
            "# Context",
            f"Today is {today} ({timezone_name}); the current local time is {now}. "
            "Resolve relative wording like \"tomorrow\" or \"every morning\" against that.",
            "",
            "## The automation as it is right now "
            "(it already includes every change from earlier turns)",
            format_document(document),
            "",
            format_catalog(catalog),
            "",
            "## Last run",
            format_last_run(last_run),
        ]
    )


# ─── context gathering (DB) ──────────────────────────────────────────────────────────


async def load_last_run(session: AsyncSession, automation: Automation) -> LastRunInfo | None:
    """The automation's last run, with its failing step if it had one.

    Best effort: a run row that has since been pruned simply means no last-run context.
    """
    run_id = automation.last_run_id
    if not run_id:
        return None
    try:
        run, steps = await runs_svc.get_run(session, run_id)
    except AppError:
        return None

    failed = next((s for s in steps if s.status == "failed"), None)
    failed_info: FailedStepInfo | None = None
    if failed is not None:
        detail_source: Any = failed.trace or failed.output
        detail = ""
        if detail_source:
            try:
                detail = json.dumps(detail_source, ensure_ascii=False, default=str)
            except (TypeError, ValueError):  # pragma: no cover — defensive
                detail = str(detail_source)
        failed_info = FailedStepInfo(
            step_id=failed.step_id,
            name=failed.name or failed.step_id,
            error=failed.error,
            detail=_clip(detail, MAX_FAILURE_DETAIL_CHARS),
        )

    return LastRunInfo(
        run_id=run.id,
        status=run.status,
        trigger=run.trigger,
        error=run.error,
        failed_step=failed_info,
    )


async def build_context(
    session: AsyncSession, automation: Automation, catalog: CatalogLike
) -> str:
    """Assemble the context block for one turn: date, document, catalog, last run."""
    tz_name = await get_timezone(session)
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError, ZoneInfoNotFoundError):  # pragma: no cover — defensive
        tz_name, tz = "UTC", ZoneInfo("UTC")
    local = datetime.now(tz)
    return render_context(
        document=automation.document or {},
        catalog=catalog,
        today=local.strftime("%Y-%m-%d (%A)"),
        now=local.strftime("%H:%M"),
        timezone_name=tz_name,
        last_run=await load_last_run(session, automation),
    )


# ─── the turn ────────────────────────────────────────────────────────────────────────


@dataclass
class AssistantResult:
    """One assistant turn, as both the router and the transcript need it."""

    message: str
    applied_summary: list[str] = field(default_factory=list)
    operations_applied: int = 0
    run_id: str | None = None
    document: dict[str, Any] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)
    version_number: int = 0
    error: str | None = None


_OPS_ADAPTER: TypeAdapter[list[Operation]] = TypeAdapter(list[Operation])


def _now_ms() -> int:
    """Transcript timestamps, in the epoch milliseconds the API uses everywhere else."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _pydantic_error_text(exc: PydanticValidationError) -> str:
    """Pydantic errors as one short line, written for the model to act on."""
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "operations"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def _history_messages(entries: list[dict[str, Any]]) -> list[ChatMessage]:
    """Replay the stored transcript as chat messages.

    A turn whose operations were rejected carries the rejection in its entry; it is
    appended to the assistant's own words so a later turn can still see (and avoid)
    the mistake.
    """
    messages: list[ChatMessage] = []
    for entry in entries:
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(entry.get("content") or "")
        error = entry.get("error")
        if role == "assistant" and error:
            content = f"{content}\n[Operations rejected: {error}]"
        if not content:
            continue
        messages.append(ChatMessage(role=role, content=content))
    return messages


async def _model_ref(session: AsyncSession, automation: Automation) -> ModelRef:
    """The automation's own model, falling back to the workspace default.

    A draft can be stored in a state that no longer parses (the document is saved before
    it validates, by design), so the fallback is a real path, not a defensive one.
    """
    try:
        return AutomationDocument.model_validate(automation.document or {}).model
    except PydanticValidationError:
        settings = await get_settings_for_client(session)
        return ModelRef.model_validate(
            {"provider": settings.default_model.provider, "model": settings.default_model.model}
        )


async def _current_state(
    session: AsyncSession, automation: Automation
) -> tuple[dict[str, Any], list[ValidationIssue], int]:
    """`(document, issues, version_number)` for a turn that changed nothing."""
    number = await automations_svc.current_version_number(session, automation)
    raw = automation.document or {}
    try:
        parsed = AutomationDocument.model_validate(raw)
    except PydanticValidationError:
        return raw, [], number
    validated, issues = await automations_svc.validate_draft(session, parsed)
    return dump_document(validated), issues, number


async def chat(
    session: AsyncSession, automation: Automation, user_message: str
) -> AssistantResult:
    """Run one assistant turn against `automation`, persisting whatever it changed.

    Raises only what the provider layer raises (`NotFound` for a missing API key,
    `ProviderError` for an upstream failure or output that never matched the schema) —
    those are the API's own error responses. An edit the model got *wrong* is not an
    exception: it comes back as `AssistantResult.error` with the document untouched.
    """
    catalog = await build_catalog(session)
    context = await build_context(session, automation, catalog)
    model_ref = await _model_ref(session, automation)

    history = list(automation.assistant_messages or [])[-MAX_HISTORY_MESSAGES:]
    convo: list[ChatMessage] = [
        ChatMessage(role="system", content=f"{SYSTEM_PROMPT}\n\n{context}"),
        *_history_messages(history),
        ChatMessage(role="user", content=user_message),
    ]

    total_in = 0
    total_out = 0
    message = ""
    run_test = False
    rejection: str | None = None
    applied: tuple[dict[str, Any], list[ValidationIssue], int, list[str]] | None = None
    ops_count = 0

    for attempt in range(MAX_ATTEMPTS):
        result = await complete_json_for(
            session,
            model_ref.provider,
            model_ref.model,
            convo,
            ASSISTANT_REPLY_SCHEMA,
            name=REPLY_TOOL_NAME,
            description=REPLY_TOOL_DESCRIPTION,
        )
        total_in += result.input_tokens
        total_out += result.output_tokens

        reply = result.data
        message = str(reply.get("message") or "")
        run_test = bool(reply.get("run_test"))
        raw_ops = reply.get("operations") or []
        rejection = None

        if not raw_ops:
            break

        try:
            ops = _OPS_ADAPTER.validate_python(raw_ops)
            document, issues, number, summary = await automations_svc.apply_ops(
                session, automation, ops, created_by="assistant"
            )
        except PydanticValidationError as exc:
            rejection = _pydantic_error_text(exc)
        except (ValueError, AppError) as exc:
            # `apply_ops` turns a malformed batch into `BadRequest` and writes nothing;
            # a bare `ValueError` would mean `apply_operations` raised past it.
            rejection = getattr(exc, "detail", None) or str(exc)
        else:
            applied = (dump_document(document), issues, number, summary)
            ops_count = len(ops)
            break

        log.info(
            "assistant_operations_rejected",
            automation_id=automation.id,
            attempt=attempt,
            reason=rejection,
        )
        if attempt + 1 >= MAX_ATTEMPTS:
            break
        convo = [
            *convo,
            ChatMessage(
                role="assistant",
                content=json.dumps(reply, ensure_ascii=False, default=str),
            ),
            ChatMessage(role="user", content=RETRY_INSTRUCTION.format(error=rejection)),
        ]

    await record_usage(
        session,
        provider=model_ref.provider,
        model=model_ref.model,
        input_tokens=total_in,
        output_tokens=total_out,
        conversation_id=automation.id,
    )

    if applied is not None:
        document, issues, version_number, summary = applied
    else:
        document, issues, version_number = await _current_state(session, automation)
        summary = []

    async def persist(final_message: str, run_id: str | None) -> None:
        """Append this turn to the transcript and commit.

        Reassigns `assistant_messages` rather than appending to it: SQLAlchemy does not
        track in-place mutation of a plain JSONB list.
        """
        ts = _now_ms()
        entries = [
            *(automation.assistant_messages or []),
            {"role": "user", "content": user_message, "ts": ts},
            {
                "role": "assistant",
                "content": final_message,
                "ts": ts,
                "summary": summary,
                "runId": run_id,
                **({"error": rejection} if rejection else {}),
            },
        ]
        automation.assistant_messages = entries[-MAX_STORED_MESSAGES:]
        await session.flush()
        await session.commit()

    run_id: str | None = None
    # A turn whose edits were rejected is not the moment to start a run: the user would be
    # testing an automation that is not the one they just asked for.
    if run_test and rejection is None:
        # Same hand-off dance as `POST /{id}/runs`: the lock is held across the commit,
        # or two turns would each find no active run and both queue one. A run already in
        # flight is not a failure here — the user asked for a test, and being told one is
        # already running beats losing the whole turn to a 409.
        async with runs_svc.creation_lock(automation.id):
            try:
                run = await runs_svc.create_run(session, automation, trigger="test")
            except Conflict:
                message = f"{message} {RUN_BUSY_NOTE}".strip()
            else:
                run_id = run.id
            await persist(message, run_id)
        if run_id is not None:
            executor.start_run_in_background(run_id)
    else:
        await persist(message, run_id)

    log.info(
        "assistant_turn",
        automation_id=automation.id,
        operations=ops_count,
        rejected=bool(rejection),
        run_id=run_id,
        version=version_number,
    )
    return AssistantResult(
        message=message,
        applied_summary=summary,
        operations_applied=ops_count,
        run_id=run_id,
        document=document,
        issues=issues,
        version_number=version_number,
        error=rejection,
    )


async def clear_history(session: AsyncSession, automation: Automation) -> None:
    """Forget the conversation so the user can start over. The document is untouched."""
    automation.assistant_messages = []
    await session.flush()
