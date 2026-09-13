"""Run lifecycle persistence: creating runs, listing history, restart recovery, pruning.

A run is a snapshot: it pins `version_id` at creation time and lays out one `pending`
`run_steps` row per step of *that* version's document, in order. Editing the automation
afterwards can never change what a run in flight is executing, and the run detail view
stays meaningful long after the document has moved on.

Executing those steps is Task 4b's job (`app.services.executor`); everything here is the
state around it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation, AutomationVersion, Run, RunStep
from app.errors import Conflict, NotFound
from app.services import executor, run_events

log = structlog.get_logger("app.runs")

ACTIVE_RUN_STATUSES = ("queued", "running")
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_STEP_STATUSES = ("pending", "running")

RESTART_ERROR = "Interrupted by server restart"

DEFAULT_RUN_LIMIT = 50
DEFAULT_KEEP_RUNS = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _duration_ms_expr(now: datetime) -> sa.ColumnElement[int]:
    """`now - started_at` in whole milliseconds, as SQL; NULL when never started.

    Used by the bulk UPDATE in `mark_orphaned_runs_failed`, which is fixing up rows it
    never loaded and so has no Python-side `started_at` to subtract from.
    """
    return sa.cast(sa.extract("epoch", now - Run.started_at) * 1000, sa.Integer)


async def _active_run(session: AsyncSession, automation_id: str) -> Run | None:
    return (
        await session.execute(
            select(Run)
            .where(Run.automation_id == automation_id, Run.status.in_(ACTIVE_RUN_STATUSES))
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_run(session: AsyncSession, automation: Automation, *, trigger: str) -> Run:
    """Queue a run of the automation's current version.

    Raises `Conflict` (409) when a run of this automation is already queued or running —
    one automation executes at most one run at a time, so steps that mutate shared state
    (send an email, write a row) can't interleave with themselves.
    """
    active = await _active_run(session, automation.id)
    if active is not None:
        raise Conflict(
            f"Automation {automation.id} already has a {active.status} run.",
            extra={"runId": active.id},
        )

    version_id = automation.current_version_id
    document: dict[str, Any] = automation.document or {}
    if version_id:
        version = (
            await session.execute(
                select(AutomationVersion).where(AutomationVersion.id == version_id)
            )
        ).scalar_one_or_none()
        if version is None:
            version_id = None
        else:
            document = version.document or {}

    run = Run(
        id=_new_id(),
        automation_id=automation.id,
        version_id=version_id,
        trigger=trigger,
        status="queued",
        input_tokens=0,
        output_tokens=0,
        created_at=_now(),
    )
    session.add(run)
    await session.flush()

    for index, step in enumerate(document.get("steps") or []):
        session.add(
            RunStep(
                id=_new_id(),
                run_id=run.id,
                step_id=step.get("id", f"step_{index}"),
                index=index,
                name=step.get("name") or "",
                type=step.get("type") or "",
                status="pending",
                attempt=0,
                trace=[],
            )
        )

    automation.last_run_id = run.id
    automation.last_run_status = run.status
    await session.flush()
    log.info("run_created", run_id=run.id, automation_id=automation.id, trigger=trigger)
    return run


async def list_runs(
    session: AsyncSession,
    automation_id: str,
    limit: int = DEFAULT_RUN_LIMIT,
    before: int | None = None,
) -> list[Run]:
    """Newest-first page of runs. `before` is a `createdAt` epoch-ms cursor (exclusive)."""
    stmt = (
        select(Run)
        .where(Run.automation_id == automation_id)
        .order_by(Run.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if before is not None:
        stmt = stmt.where(Run.created_at < datetime.fromtimestamp(before / 1000, tz=timezone.utc))
    return list((await session.execute(stmt)).scalars().all())


async def get_run(session: AsyncSession, run_id: str) -> tuple[Run, list[RunStep]]:
    run = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFound(f"Run {run_id} not found.")
    steps = list(
        (
            await session.execute(
                select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.index)
            )
        )
        .scalars()
        .all()
    )
    return run, steps


async def mark_orphaned_runs_failed(session: AsyncSession) -> int:
    """Fail every run left mid-flight by a crash or restart.

    Runs live in the API process, so a restart means nothing is executing them any more;
    without this they would sit in `running` forever and block `create_run` with a 409.
    Returns the number of runs failed.
    """
    orphan_ids = list(
        (
            await session.execute(select(Run.id).where(Run.status.in_(ACTIVE_RUN_STATUSES)))
        )
        .scalars()
        .all()
    )
    if not orphan_ids:
        return 0

    now = _now()
    await session.execute(
        update(RunStep)
        .where(RunStep.run_id.in_(orphan_ids), RunStep.status.in_(ACTIVE_STEP_STATUSES))
        .values(status="cancelled", ended_at=now)
    )
    await session.execute(
        update(Run)
        .where(Run.id.in_(orphan_ids))
        .values(
            status="failed",
            error=RESTART_ERROR,
            ended_at=now,
            # Same wall-clock measure `cancel_run` records; a run that never started has
            # no elapsed time to report, so it keeps a NULL duration.
            duration_ms=_duration_ms_expr(now),
        )
    )
    await session.execute(
        update(Automation)
        .where(Automation.last_run_id.in_(orphan_ids))
        .values(last_run_status="failed")
    )
    log.info("orphaned_runs_failed", count=len(orphan_ids))
    return len(orphan_ids)


async def prune_runs(
    session: AsyncSession, automation_id: str, keep: int = DEFAULT_KEEP_RUNS
) -> int:
    """Drop all but the `keep` newest runs of an automation (steps cascade). Returns the
    number of runs deleted."""
    keep = max(0, keep)
    survivors = (
        select(Run.id)
        .where(Run.automation_id == automation_id)
        .order_by(Run.created_at.desc())
        .limit(keep)
        .scalar_subquery()
    )
    result = await session.execute(
        delete(Run).where(Run.automation_id == automation_id, Run.id.not_in(survivors))
    )
    deleted = result.rowcount or 0
    if deleted:
        log.info("runs_pruned", automation_id=automation_id, deleted=deleted)
    return deleted


async def cancel_run(session: AsyncSession, run_id: str) -> str:
    """Cancel a run, returning its resulting status.

    A `queued` run has not started, so it is cancelled outright here. A `running` run is
    owned by the executor, which has to unwind the step it's inside — we only signal it
    (Task 4b) and leave it `running` until it reports back. Terminal runs are returned
    unchanged; cancelling twice is not an error.
    """
    run = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFound(f"Run {run_id} not found.")

    if run.status in TERMINAL_RUN_STATUSES:
        return run.status

    if run.status == "queued":
        now = _now()
        run.status = "cancelled"
        run.ended_at = now
        if run.started_at is not None:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
        await session.execute(
            update(RunStep)
            .where(RunStep.run_id == run.id, RunStep.status.in_(ACTIVE_STEP_STATUSES))
            .values(status="cancelled", ended_at=now)
        )
        await session.execute(
            update(Automation)
            .where(Automation.last_run_id == run.id)
            .values(last_run_status="cancelled")
        )
        await session.flush()
        # Anyone watching this run over SSE is waiting on a queue that will never receive
        # another event — end their stream instead of leaving it open until they give up.
        run_events.close(run.id)
        log.info("run_cancelled", run_id=run.id)
        return run.status

    executor.request_cancel(run.id)
    return run.status
