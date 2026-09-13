"""The automation builder's assistant: one LLM turn that *edits* the automation.

The assistant never writes prose the client has to interpret. Every turn produces the
same structured reply — an `intent`, a `message` for the user, the `operations` to apply
to the document, and a `run_test` flag — and this module is what turns that reply into a
new document version, a test run, and a persisted transcript. The contract itself and
every word the model is told live in `app.services.assistant_prompt`, which is pure.

Four decisions shape the module:

1. **The operations are the API.** The payload is schema-checked by `app.llm.structured`,
   re-validated by Pydantic here, and then applied through the same `apply_ops` the human
   builder uses — the assistant gets no privileged path into the document. `intent` is
   checked against what was actually sent: an `answer` turn that returned operations
   anyway has them dropped, because a question must never move the document.

2. **A bad edit is a prompt problem, not a user problem.** Two things can go wrong after
   the model replies: `apply_ops` can refuse the whole batch (an unknown step id, an
   out-of-range index — nothing is written), or the batch can apply and leave
   *error-level validation issues* behind (an action that doesn't exist, a dangling
   `{{ref}}`). Either way the turn spends its one self-correction: the problem goes back
   to the model, which fixes it in a second call. What the client gets back is never raw
   Pydantic text — `error` is a fixed sentence, and the detail goes to the retry prompt
   and the logs.

3. **A run's output is untrusted input.** A step can fetch a web page or read an email,
   so everything a run recorded reaches the model inside `<untrusted_run_output>` fences,
   in a *user* message rather than the system prompt, summarized by shape rather than
   pasted in full.

4. **An unreadable draft never reaches the model.** The document is parsed once, at the
   top; a draft that no longer validates gets a specific answer ("restore an earlier
   version") and costs nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation
from app.errors import AppError, BadRequest, Conflict, ValidationFailure
from app.llm.base import ChatMessage
from app.llm.structured import complete_json_for
from app.schemas.documents import AutomationDocument, Operation, ValidationIssue
from app.services import automations as automations_svc
from app.services import executor
from app.services import runs as runs_svc
from app.services.assistant_prompt import (
    ASSISTANT_REPLY_SCHEMA,
    REPLY_TOOL_DESCRIPTION,
    REPLY_TOOL_NAME,
    CatalogLike,
    FailedStepInfo,
    LastRunInfo,
    describe_shape,
    format_document,
    render_context,
    render_system,
)
from app.services.catalog import build_catalog
from app.services.documents import dump_document, validate_document
from app.services.settings import get_timezone
from app.services.usage import record_usage

log = structlog.get_logger("app.assistant")

__all__ = [
    "AssistantResult",
    "build_context",
    "chat",
    "clear_history",
    "load_last_run",
]

# How many past transcript entries are replayed to the model, and how many characters of
# them. The document is in the context on every turn, so older turns mostly add tokens.
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CHARS = 12_000
# How many entries are *kept* in the database. Bounded so a long-lived automation's JSONB
# column cannot grow without limit.
MAX_STORED_MESSAGES = 100

# One self-correction per turn, spent on whichever problem comes first: a batch
# `apply_ops` refused, or a batch that applied but left error-level issues behind.
MAX_CORRECTIONS = 1

# What the *client* is told. The model's own rejection text can quote its payload (and
# with it whatever the user typed), so it never leaves the retry prompt and the logs.
REJECTED_ERROR = (
    "I couldn't apply that change to your automation, so nothing was modified. "
    "Try describing what you want a little differently."
)
UNREADABLE_DOCUMENT_ERROR = (
    "I can't read this automation's saved document, so I can't safely edit it. "
    "Restore an earlier version from the version history and I'll pick it up from there."
)
ISSUES_CAVEAT = "Some fields still need attention in the editor."
CORRECTION_FAILED_CAVEAT = (
    "I tried to fix the remaining issues but couldn't; please check the highlighted fields."
)

RETRY_INSTRUCTION = (
    "Your operations were rejected and nothing was changed: {error} "
    "Fix them and call the tool again. Keep the same intent; only correct the "
    "operations themselves (step ids must already exist for update/remove/move, new "
    "step ids must be unique, indexes must be within range)."
)
ISSUES_INSTRUCTION = (
    "Your operations were applied, but the automation now has problems that make it "
    "unrunnable:\n{issues}\n\nHere is the automation as it stands now:\n{document}\n\n"
    "Call the tool again with operations that fix those problems, applied on top of "
    "what is above. Do not repeat the edits you already made. If a problem is that an "
    "integration is not connected, leave it and say so in your message instead."
)
HISTORY_REJECTION_NOTE = "[Those operations were rejected; nothing was applied.]"

RUN_BUSY_NOTE = "This automation already has a run in progress, so I didn't start a new one."


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


@dataclass
class _Applied:
    """Everything that actually landed on the document this turn.

    A turn can apply *two* batches (the model's first, then its self-correction), and
    what the user is shown has to be the whole edit: `operations` and `summary`
    accumulate across both, while `document`, `issues` and `version_number` are simply
    the latest state. `message` is the reply that accompanied the most recent batch that
    applied — not the one that was refused afterwards.
    """

    document: dict[str, Any]
    issues: list[ValidationIssue]
    version_number: int
    summary: list[str]
    operations: int
    message: str

    def then(
        self,
        *,
        document: dict[str, Any],
        issues: list[ValidationIssue],
        version_number: int,
        summary: list[str],
        operations: int,
        message: str,
    ) -> _Applied:
        """This outcome, followed by a second batch that also applied."""
        return _Applied(
            document=document,
            issues=issues,
            version_number=version_number,
            summary=[*self.summary, *summary],
            operations=self.operations + operations,
            message=message,
        )


_OPS_ADAPTER: TypeAdapter[list[Operation]] = TypeAdapter(list[Operation])


# ─── context gathering (DB) ──────────────────────────────────────────────────────────


async def load_last_run(session: AsyncSession, automation: Automation) -> LastRunInfo | None:
    """The automation's last run, with its failing step if it had one.

    The step's recorded trace/output is reduced to a *shape* (`describe_shape`) rather
    than carried through: it is the one part of the prompt that can be arbitrarily large
    and is written by whatever the run touched.

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
        recorded = failed.trace or failed.output
        failed_info = FailedStepInfo(
            step_id=failed.step_id,
            name=failed.name or failed.step_id,
            error=failed.error,
            output_shape=describe_shape(recorded) if recorded else "",
        )

    return LastRunInfo(
        run_id=run.id,
        status=run.status,
        trigger=run.trigger,
        error=run.error,
        failed_step=failed_info,
    )


async def build_context(session: AsyncSession, automation: Automation) -> str:
    """The context message for one turn: today's date, the document, the last run.

    The action catalog is *not* here — it is first-party text and belongs in the system
    message (`render_system`), while everything this function gathers is content the
    automation and its runs produced.
    """
    tz_name = await get_timezone(session)
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError, ZoneInfoNotFoundError):  # pragma: no cover — defensive
        tz_name, tz = "UTC", ZoneInfo("UTC")
    local = datetime.now(tz)
    return render_context(
        document=automation.document or {},
        today=local.strftime("%Y-%m-%d (%A)"),
        now=local.strftime("%H:%M"),
        timezone_name=tz_name,
        last_run=await load_last_run(session, automation),
    )


# ─── helpers ─────────────────────────────────────────────────────────────────────────


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


def _format_issues(issues: list[ValidationIssue]) -> str:
    return "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)


def _history_messages(
    entries: list[dict[str, Any]],
    *,
    max_entries: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[ChatMessage]:
    """Replay the stored transcript, newest-first within both budgets.

    Two caps, because either one alone is the wrong bound: twenty turns of one-line
    questions is nothing, and three turns that each quoted a long email is too much.
    A turn whose operations were rejected is replayed with a fixed note, so the model
    can see it went wrong without the rejection text being handed back to it verbatim.
    """
    selected: list[ChatMessage] = []
    used = 0
    for entry in reversed(entries[-max_entries:]):
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(entry.get("content") or "")
        if role == "assistant" and entry.get("error"):
            content = f"{content}\n{HISTORY_REJECTION_NOTE}".strip()
        if not content:
            continue
        if used + len(content) > max_chars and selected:
            break
        used += len(content)
        selected.append(ChatMessage(role=role, content=content))
    return list(reversed(selected))


def _current_state(
    automation: Automation,
    doc: AutomationDocument,
    catalog: CatalogLike,
    version_number: int,
) -> tuple[dict[str, Any], list[ValidationIssue], int]:
    """`(document, issues, version_number)` for a turn that changed nothing.

    Validated against the catalog the turn already built rather than through
    `automations_svc.validate_draft`, which would assemble a second one.
    """
    validated, issues = validate_document(doc, catalog)  # type: ignore[arg-type]
    return dump_document(validated), issues, version_number


# ─── the turn ────────────────────────────────────────────────────────────────────────


async def chat(
    session: AsyncSession, automation: Automation, user_message: str
) -> AssistantResult:
    """Run one assistant turn against `automation`, persisting whatever it changed.

    Raises only what the provider layer raises (`NotFound` for a missing API key,
    `ProviderError` for an upstream failure or output that never matched the schema) —
    those are the API's own error responses, and nothing has been committed when they
    happen, so the transcript and the document are left exactly as they were. An edit
    the model got *wrong* is not an exception: it comes back as `AssistantResult.error`
    (a fixed, user-facing sentence) with the document untouched.
    """
    version_number = await automations_svc.current_version_number(session, automation)

    # Parsed once, before anything is spent: a draft that no longer validates cannot be
    # patched by operations (they are applied to a parsed document), and telling the user
    # so is both the honest answer and free.
    try:
        doc = AutomationDocument.model_validate(automation.document or {})
    except PydanticValidationError as exc:
        log.warning(
            "assistant_document_unparseable", automation_id=automation.id, error=str(exc)
        )
        await _persist(
            session,
            automation,
            user_message=user_message,
            message=UNREADABLE_DOCUMENT_ERROR,
            summary=[],
            run_id=None,
            error=UNREADABLE_DOCUMENT_ERROR,
        )
        return AssistantResult(
            message=UNREADABLE_DOCUMENT_ERROR,
            document=automation.document or {},
            version_number=version_number,
            error=UNREADABLE_DOCUMENT_ERROR,
        )

    catalog = await build_catalog(session)
    convo: list[ChatMessage] = [
        ChatMessage(role="system", content=render_system(catalog)),
        ChatMessage(role="user", content=await build_context(session, automation)),
        *_history_messages(list(automation.assistant_messages or [])),
        ChatMessage(role="user", content=user_message),
    ]

    model_ref = doc.model
    total_in = 0
    total_out = 0
    message = ""
    run_test = False
    rejection: str | None = None
    applied: _Applied | None = None
    corrections = MAX_CORRECTIONS

    try:
        while True:
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
            intent = str(reply.get("intent") or "edit")
            message = str(reply.get("message") or "")
            # Both default in the schema: a model that means "no changes, no test run"
            # routinely omits them, and that is the commonest reply there is.
            run_test = bool(reply.get("run_test", False))
            raw_ops = reply.get("operations") or []
            rejection = None

            if intent == "answer" and raw_ops:
                # The model said it was answering a question and then edited anyway. The
                # stated intent wins: an answer must never move the document.
                log.warning(
                    "assistant_intent_mismatch",
                    automation_id=automation.id,
                    operations=len(raw_ops),
                )
                raw_ops = []

            if not raw_ops:
                break

            try:
                ops = _OPS_ADAPTER.validate_python(raw_ops)
                document, issues, number, summary = await automations_svc.apply_ops(
                    session, automation, ops, created_by="assistant"
                )
            except PydanticValidationError as exc:
                # Listed first: `pydantic.ValidationError` is itself a `ValueError`.
                rejection = _pydantic_error_text(exc)
            except (BadRequest, ValidationFailure, ValueError) as exc:
                # `apply_ops` turns a malformed batch into `BadRequest` and writes
                # nothing; a bare `ValueError` would mean `apply_operations` raised
                # past it. Anything else is a real failure and propagates.
                rejection = getattr(exc, "detail", None) or str(exc)
            else:
                landed = {
                    "document": dump_document(document),
                    "issues": issues,
                    "version_number": number,
                    "summary": summary,
                    "operations": len(ops),
                    "message": message,
                }
                applied = (
                    _Applied(**landed) if applied is None else applied.then(**landed)
                )
                errors = [i for i in issues if i.level == "error"]
                if not errors or not corrections:
                    break
                # Applied, but the automation cannot run as it now stands. The edits
                # stay (they are versioned and the user can see them); the correction
                # turn is told what is broken and applies its fixes on top.
                corrections -= 1
                log.info(
                    "assistant_document_has_errors",
                    automation_id=automation.id,
                    issues=len(errors),
                )
                convo = [
                    *convo,
                    ChatMessage(
                        role="assistant",
                        content=json.dumps(reply, ensure_ascii=False, default=str),
                    ),
                    ChatMessage(
                        role="user",
                        content=ISSUES_INSTRUCTION.format(
                            issues=_format_issues(errors),
                            document=format_document(applied.document),
                        ),
                    ),
                ]
                continue

            log.info(
                "assistant_operations_rejected",
                automation_id=automation.id,
                reason=rejection,
                corrections_left=corrections,
            )
            if not corrections:
                break
            corrections -= 1
            convo = [
                *convo,
                ChatMessage(
                    role="assistant",
                    content=json.dumps(reply, ensure_ascii=False, default=str),
                ),
                ChatMessage(role="user", content=RETRY_INSTRUCTION.format(error=rejection)),
            ]
    finally:
        # In a `finally` so a turn that dies mid-way still bills what it spent. Whether
        # it survives depends on the caller's transaction: the request dependency rolls
        # back on an exception, which is also what keeps the transcript consistent.
        await record_usage(
            session,
            provider=model_ref.provider,
            model=model_ref.model,
            input_tokens=total_in,
            output_tokens=total_out,
            conversation_id=automation.id,
            source="assistant",
        )

    if applied is not None:
        document = applied.document
        issues = applied.issues
        version_number = applied.version_number
        summary, ops_count = applied.summary, applied.operations
        error = None
        # The message describes the edit that landed, so it comes from the batch that
        # landed — a correction that was refused afterwards described work that does not
        # exist. Either way the user is told the automation still needs attention: never
        # report success silently.
        message = applied.message
        if rejection is not None:
            message = f"{message} {CORRECTION_FAILED_CAVEAT}".strip()
        elif any(i.level == "error" for i in issues):
            message = f"{message} {ISSUES_CAVEAT}".strip()
    else:
        document, issues, version_number = _current_state(
            automation, doc, catalog, version_number
        )
        summary, ops_count = [], 0
        error = REJECTED_ERROR if rejection is not None else None

    run_id: str | None = None
    # A turn whose edits were rejected outright is not the moment to start a run: the
    # user would be testing an automation that is not the one they just asked for.
    if run_test and error is None:
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
            await _persist(
                session,
                automation,
                user_message=user_message,
                message=message,
                summary=summary,
                run_id=run_id,
                error=error,
            )
        if run_id is not None:
            executor.start_run_in_background(run_id)
    else:
        await _persist(
            session,
            automation,
            user_message=user_message,
            message=message,
            summary=summary,
            run_id=run_id,
            error=error,
        )

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
        error=error,
    )


async def _persist(
    session: AsyncSession,
    automation: Automation,
    *,
    user_message: str,
    message: str,
    summary: list[str],
    run_id: str | None,
    error: str | None,
) -> None:
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
            "content": message,
            "ts": ts,
            "summary": summary,
            "runId": run_id,
            **({"error": error} if error else {}),
        },
    ]
    automation.assistant_messages = entries[-MAX_STORED_MESSAGES:]
    await session.flush()
    await session.commit()


async def clear_history(session: AsyncSession, automation: Automation) -> None:
    """Forget the conversation so the user can start over. The document is untouched."""
    automation.assistant_messages = []
    await session.flush()
