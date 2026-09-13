"""The run executor: walks a run's snapshotted document step by step.

One `asyncio.Task` per run, owned by this process. It reads the **pinned version's**
document (never the live draft — a run must execute what it was started against), walks
its steps in order, and writes the `run_steps` row plus a `run_events` event after every
state change, so both the polling endpoint and the SSE stream see progress as it happens
rather than at the end.

Around each step sits a retry loop with exponential backoff. Only failures a retry could
plausibly fix are retried: a tool that returned `ok=False`, an upstream provider blip, a
timeout. A dangling `{{ref}}`, an unusable output schema or a model that cannot produce
valid output are deterministic — retrying them burns tokens to fail again — so they fail
the step on the first attempt.

The run's own state machine is simple: `queued` → `running` → one of `succeeded`,
`failed` or `cancelled`. A `filter` step that decides against continuing is *not* a
failure: it marks the remaining steps `skipped`, records `stopped_by_step_id` and the run
still succeeds. Whatever happens, `execute_run` finalizes the run row, records usage,
prunes old history and closes the event topic — a client watching the stream always gets a
terminal `run_finished`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import Automation, AutomationVersion, Run, RunStep
from app.errors import AppError, ProviderError, ValidationFailure
from app.llm.base import LLMProvider
from app.llm.factory import get_provider_for
from app.schemas.documents import AutomationDocument, RetryPolicy, ScheduleTrigger, Step
from app.services import run_events, step_runner
from app.services.refs import RefError
from app.services.settings import get_timezone
from app.services.step_runner import StepContext, StepFailure, Usage
from app.services.usage import record_usage

log = structlog.get_logger("app.executor")

# Every run currently executing in this process, keyed by run id. `request_cancel` reaches
# into it; the lifespan cancels whatever is left at shutdown.
RUNNING_TASKS: dict[str, asyncio.Task[None]] = {}

# Patched to a no-op in tests so a backoff doesn't make the suite wait for real.
_sleep = asyncio.sleep

# A run is a background job with no user watching for most of its life; this is the
# backstop against one wedged forever on a step that never returns.
RUN_TIMEOUT_SECONDS = 20 * 60
RUN_TIMEOUT_ERROR = "Run exceeded 20 minutes"

# Per-step-type defaults, used when a step declares neither of its own.
DEFAULT_RETRY: dict[str, RetryPolicy] = {
    "action": RetryPolicy(max_attempts=3, backoff_seconds=10),
    "ai": RetryPolicy(max_attempts=2, backoff_seconds=10),
    # A filter is pure (rules) or one structured call (ai): nothing a retry helps with.
    "filter": RetryPolicy(max_attempts=1, backoff_seconds=0),
}
DEFAULT_TIMEOUT_SECONDS: dict[str, int] = {"action": 120, "ai": 300, "filter": 60}

MAX_BACKOFF_SECONDS = 120

# Outputs up to this size ride along on the `step_finished` event; bigger ones are only
# previewed, and the client re-reads the run detail if it wants the whole thing.
EVENT_OUTPUT_CHARS = 2_000

# How many runs of an automation are kept after each run finishes.
RUN_HISTORY_LIMIT = 200

ERROR_CHARS = 2_000

RUN_STEP_ACTIVE = ("pending", "running")


class _RunFailed(Exception):
    """A step failed for good; the run stops here."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms_since(start: datetime | None, end: datetime) -> int | None:
    return None if start is None else int((end - start).total_seconds() * 1000)


def _describe(exc: BaseException) -> str:
    """A one-line, storable rendering of whatever went wrong."""
    detail = exc.detail if isinstance(exc, AppError) else str(exc)
    if not detail:
        detail = type(exc).__name__
    if isinstance(exc, TimeoutError):
        detail = "Timed out"
    return step_runner.clip(detail, ERROR_CHARS)


def _is_retryable(exc: BaseException) -> bool:
    """Whether another attempt could plausibly do better.

    Deterministic failures — a reference that doesn't resolve, a schema the model can't
    satisfy, an output that was truncated by the token limit, a missing API key — fail on
    the first attempt. Everything else (tool failures, upstream errors, timeouts) retries.
    """
    if isinstance(exc, (RefError, ValidationFailure, NotImplementedError)):
        return False
    if isinstance(exc, ProviderError):
        return exc.extra.get("reason") == "upstream"
    if isinstance(exc, AppError):
        # BadRequest / NotFound (no API key configured) / ToolNotConfigured — all of them
        # need a human to change something before a retry means anything.
        return False
    return True


async def resolve_provider(session: AsyncSession, provider_name: str) -> LLMProvider:
    """The provider a run's model calls. Module-level so tests can swap it wholesale."""
    return await get_provider_for(session, provider_name)


# ─── task management ─────────────────────────────────────────────────────────────────


def start_run_in_background(run_id: str) -> asyncio.Task[None]:
    """Kick off execution of an already-created, committed `queued` run.

    Returns the task, mostly so tests can await it. Calling twice for the same run id
    returns the task already in flight rather than starting a second one.
    """
    existing = RUNNING_TASKS.get(run_id)
    if existing is not None and not existing.done():
        return existing

    task = asyncio.create_task(execute_run(run_id), name=f"run:{run_id}")
    RUNNING_TASKS[run_id] = task
    task.add_done_callback(lambda t: _on_task_done(run_id, t))
    return task


def _on_task_done(run_id: str, task: asyncio.Task[None]) -> None:
    if RUNNING_TASKS.get(run_id) is task:
        RUNNING_TASKS.pop(run_id, None)
    if task.cancelled():
        log.info("run_task_cancelled", run_id=run_id)
        return
    exc = task.exception()
    if exc is not None:
        # `execute_run` handles its own failures; anything escaping it is a bug here.
        log.error("run_task_crashed", run_id=run_id, exc_info=exc)


def request_cancel(run_id: str) -> bool:
    """Ask a run executing in this process to stop. True when one was signalled."""
    task = RUNNING_TASKS.get(run_id)
    if task is None or task.done():
        return False
    log.info("run_cancel_requested", run_id=run_id)
    return task.cancel()


async def cancel_all(timeout: float = 5.0) -> None:
    """Cancel every in-flight run and wait briefly for the cleanup. Used at shutdown."""
    tasks = [t for t in RUNNING_TASKS.values() if not t.done()]
    if not tasks:
        return
    log.info("cancelling_runs", count=len(tasks))
    for task in tasks:
        task.cancel()
    await asyncio.wait(tasks, timeout=timeout)


# ─── run execution ───────────────────────────────────────────────────────────────────


def build_ctx(document: AutomationDocument, workspace_timezone: str) -> dict[str, Any]:
    """The `trigger.*` context every reference and prompt sees.

    An automation with a schedule trigger runs "in" that trigger's timezone; anything else
    falls back to the workspace timezone. `now`/`date` are rendered in it so `{{trigger.date}}`
    in a step means the same day the schedule fired, not a UTC day that may already have
    rolled over.
    """
    tz_name = None
    if isinstance(document.trigger, ScheduleTrigger):
        tz_name = document.trigger.settings.timezone
    tz_name = tz_name or workspace_timezone or "UTC"
    try:
        tz: Any = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — an unknown tz must never kill a run
        log.warning("unknown_timezone", timezone=tz_name)
        tz_name, tz = "UTC", timezone.utc
    now = datetime.now(tz)
    return {"now": now.isoformat(), "date": now.strftime("%Y-%m-%d"), "timezone": tz_name}


async def _load_document(session: AsyncSession, run: Run, automation: Automation) -> Any:
    """The document this run executes: its pinned version's, never the live draft."""
    if run.version_id:
        version = await session.get(AutomationVersion, run.version_id)
        if version is not None:
            return version.document or {}
    return automation.document or {}


async def execute_run(run_id: str) -> None:
    """Execute one run to a terminal state. Never raises — failures land on the run row."""
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            log.warning("run_missing", run_id=run_id)
            return
        if run.status != "queued":
            # Already running, or finished/cancelled before we got the loop's attention.
            log.info("run_not_queued", run_id=run_id, status=run.status)
            return

        automation = await session.get(Automation, run.automation_id)
        if automation is None:
            log.warning("run_automation_missing", run_id=run_id)
            return

        rows = list(
            (
                await session.execute(
                    select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.index)
                )
            )
            .scalars()
            .all()
        )

        run.status = "running"
        run.started_at = _now()
        automation.last_run_id = run.id
        automation.last_run_status = "running"
        await session.commit()
        run_events.publish(
            run_id, {"type": "run_started", "runId": run_id, "status": "running"}
        )
        log.info("run_started", run_id=run_id, automation_id=automation.id)

        execution = _Execution(session=session, run=run, automation=automation, rows=rows)
        status = "succeeded"
        error: str | None = None
        try:
            document = AutomationDocument.model_validate(
                await _load_document(session, run, automation)
            )
        except PydanticValidationError as exc:
            first = (exc.errors() or [{}])[0]
            status = "failed"
            error = f"Automation document is not executable: {first.get('msg', exc)}"
            await execution.skip_from(0)
        else:
            execution.document = document
            execution.ctx = build_ctx(document, await get_timezone(session))
            try:
                await asyncio.wait_for(execution.run_steps(), timeout=RUN_TIMEOUT_SECONDS)
            except _RunFailed as exc:
                status, error = "failed", str(exc)
            except TimeoutError:
                status, error = "failed", RUN_TIMEOUT_ERROR
                await execution.abort("failed", RUN_TIMEOUT_ERROR)
            except asyncio.CancelledError:
                # Swallowed rather than re-raised: the run's terminal state is recorded
                # below and the caller (`cancel_run`, or shutdown) only ever wanted the
                # work to stop. Re-raising would leave the task `cancelled` with its
                # cleanup already done, which reads as a crash in the done-callback and
                # gives `cancel_all` nothing useful to wait on.
                status, error = "cancelled", None
                await execution.abort("cancelled", None)
                log.info("run_cancelled", run_id=run_id)
            except Exception as exc:  # noqa: BLE001 — a bug here must still finalize the run
                log.error("run_crashed", run_id=run_id, exc_info=True)
                status, error = "failed", _describe(exc)
                await execution.abort("failed", error)
        finally:
            await execution.finalize(status, error)


class _Execution:
    """Mutable state of one run in flight: the step rows, outputs so far, and tokens."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        run: Run,
        automation: Automation,
        rows: list[RunStep],
    ) -> None:
        self.session = session
        self.run = run
        self.automation = automation
        self.rows = rows
        self.document: AutomationDocument | None = None
        self.ctx: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}
        self.usage = Usage()
        self.current = 0
        self._provider: LLMProvider | None = None

    # --- plumbing ---------------------------------------------------------------------

    async def get_provider(self) -> LLMProvider:
        """The run's provider, resolved once and reused by every model call."""
        if self._provider is None:
            assert self.document is not None
            self._provider = await resolve_provider(
                self.session, self.document.model.provider
            )
        return self._provider

    async def skip_from(self, index: int) -> None:
        """Mark every step from `index` on as `skipped` and announce each one."""
        now = _now()
        for row in self.rows[index:]:
            if row.status not in RUN_STEP_ACTIVE:
                continue
            row.status = "skipped"
            row.ended_at = now
            run_events.publish(
                self.run.id,
                {
                    "type": "step_finished",
                    "stepId": row.step_id,
                    "index": row.index,
                    "status": "skipped",
                },
            )
        await self.session.commit()

    async def abort(self, status: str, error: str | None) -> None:
        """End a run that was cut short: the step in flight takes `status`, the rest skip."""
        if self.current < len(self.rows):
            row = self.rows[self.current]
            if row.status in RUN_STEP_ACTIVE:
                now = _now()
                row.status = status
                row.error = error
                row.ended_at = now
                row.duration_ms = _ms_since(row.started_at, now)
                run_events.publish(
                    self.run.id,
                    {
                        "type": "step_finished",
                        "stepId": row.step_id,
                        "index": row.index,
                        "status": status,
                        "error": error,
                    },
                )
        await self.skip_from(self.current + 1)

    # --- the loop ---------------------------------------------------------------------

    async def run_steps(self) -> None:
        assert self.document is not None
        for index, step in enumerate(self.document.steps):
            if index >= len(self.rows):
                # The run's step rows and the document it pinned disagree — only possible
                # if the rows were tampered with. Stop rather than execute blind.
                raise _RunFailed("Run steps do not match the pinned document.")
            self.current = index
            if not await self._run_one(index, step):
                return

    async def _run_one(self, index: int, step: Step) -> bool:
        """Run one step to completion. False when the run should stop here (a filter said so)."""
        row = self.rows[index]
        sctx = StepContext(
            session=self.session,
            run_id=self.run.id,
            document=self.document,  # type: ignore[arg-type]
            step=step,
            index=index,
            ctx=self.ctx,
            outputs=self.outputs,
            get_provider=self.get_provider,
            usage=self.usage,
            trace=list(row.trace or []),
        )

        retry = step.retry or DEFAULT_RETRY[step.type]
        timeout = step.timeout_seconds or DEFAULT_TIMEOUT_SECONDS[step.type]
        resolved: dict[str, Any] | None = None

        row.status = "running"
        row.started_at = _now()
        row.error = None
        await self.session.commit()

        for attempt in range(1, retry.max_attempts + 1):
            row.attempt = attempt
            await self.session.commit()
            sctx.publish("step_started", attempt=attempt)
            try:
                result, resolved = await asyncio.wait_for(
                    self._attempt(sctx, row, resolved), timeout=timeout
                )
            except Exception as exc:  # noqa: BLE001 — classified below
                message = _describe(exc)
                retrying = _is_retryable(exc) and attempt < retry.max_attempts
                delay = (
                    min(retry.backoff_seconds * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS)
                    if retrying
                    else None
                )
                entry: dict[str, Any] = {"kind": "attempt", "n": attempt, "error": message}
                if delay is not None:
                    entry["retryInSeconds"] = delay
                sctx.trace.append(entry)
                row.trace = list(sctx.trace)
                await self.session.commit()
                log.warning(
                    "step_attempt_failed",
                    run_id=self.run.id,
                    step_id=step.id,
                    attempt=attempt,
                    retrying=retrying,
                    error=message,
                )
                if delay is None:
                    await self._fail_step(row, sctx, message)
                    raise _RunFailed(message) from exc
                sctx.publish(
                    "step_retry", attempt=attempt, error=message, retryInSeconds=delay
                )
                await _sleep(delay)
                continue

            return await self._succeed_step(row, sctx, step, result)

        raise _RunFailed("Step exhausted its attempts.")  # pragma: no cover — loop returns

    async def _attempt(
        self, sctx: StepContext, row: RunStep, resolved: dict[str, Any] | None
    ) -> tuple[step_runner.StepResult, dict[str, Any] | None]:
        """One attempt: resolve the inputs if they aren't resolved yet, then execute.

        Resolution is memoized across attempts — re-running `ai_fill` would hand the action
        different arguments the second time round, so a retry repeats the *same* call.
        """
        if resolved is None:
            resolved = await step_runner.prepare_step(sctx)
            if resolved is not None:
                row.resolved_input = step_runner.redact(resolved)
                await self.session.commit()
        return await step_runner.run_step(sctx, resolved), resolved

    async def _succeed_step(
        self,
        row: RunStep,
        sctx: StepContext,
        step: Step,
        result: step_runner.StepResult,
    ) -> bool:
        now = _now()
        row.status = "succeeded"
        row.output = result.output
        row.error = None
        row.ended_at = now
        row.duration_ms = _ms_since(row.started_at, now)
        row.trace = list(sctx.trace)
        self.outputs[step.id] = result.output

        if result.stop:
            self.run.stopped_by_step_id = step.id
        await self.session.commit()

        event: dict[str, Any] = {
            "type": "step_finished",
            "stepId": step.id,
            "index": row.index,
            "status": "succeeded",
            "outputPreview": step_runner.preview(result.output),
        }
        compact = json.dumps(
            result.output, separators=(",", ":"), ensure_ascii=False, default=str
        )
        if len(compact) <= EVENT_OUTPUT_CHARS:
            event["output"] = result.output
        run_events.publish(self.run.id, event)

        if result.stop:
            log.info("run_stopped_by_filter", run_id=self.run.id, step_id=step.id)
            await self.skip_from(row.index + 1)
            return False
        return True

    async def _fail_step(self, row: RunStep, sctx: StepContext, message: str) -> None:
        now = _now()
        row.status = "failed"
        row.error = message
        row.ended_at = now
        row.duration_ms = _ms_since(row.started_at, now)
        row.trace = list(sctx.trace)
        await self.session.commit()
        sctx.publish("step_finished", status="failed", error=message)
        await self.skip_from(row.index + 1)

    # --- finalization -----------------------------------------------------------------

    async def finalize(self, status: str, error: str | None) -> None:
        """Close the run out: status, tokens, usage, history pruning, terminal event."""
        now = _now()
        run = self.run
        run.status = status
        run.error = error
        run.ended_at = now
        run.duration_ms = _ms_since(run.started_at, now)
        run.input_tokens = self.usage.input_tokens
        run.output_tokens = self.usage.output_tokens
        self.automation.last_run_id = run.id
        self.automation.last_run_status = status

        if self.document is not None:
            await record_usage(
                self.session,
                provider=self.document.model.provider,
                model=self.document.model.model,
                input_tokens=self.usage.input_tokens,
                output_tokens=self.usage.output_tokens,
                # `usage_entries.conversation_id` is a free-text correlation id with no FK;
                # the run id is what a usage row for an automation should point back at.
                conversation_id=run.id,
            )
        try:
            await self.session.commit()
        except Exception:  # noqa: BLE001 — the event below must still go out
            log.error("run_finalize_failed", run_id=run.id, exc_info=True)
            await self.session.rollback()

        try:
            # Imported here, not at module scope: `app.services.runs` imports this module
            # for `request_cancel`, so a top-level import would close the cycle.
            from app.services.runs import prune_runs

            await prune_runs(self.session, run.automation_id, keep=RUN_HISTORY_LIMIT)
            await self.session.commit()
        except Exception:  # noqa: BLE001 — pruning is housekeeping, never fatal
            log.warning("run_prune_failed", run_id=run.id, exc_info=True)
            await self.session.rollback()

        log.info(
            "run_finished",
            run_id=run.id,
            status=status,
            duration_ms=run.duration_ms,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
        )
        run_events.publish(
            run.id,
            {"type": "run_finished", "runId": run.id, "status": status, "error": error},
        )
        run_events.close(run.id)


# `StepFailure` is re-exported so callers can catch "a step failed" without reaching into
# the step runner.
__all__ = [
    "RUNNING_TASKS",
    "StepFailure",
    "build_ctx",
    "cancel_all",
    "execute_run",
    "request_cancel",
    "resolve_provider",
    "start_run_in_background",
]
