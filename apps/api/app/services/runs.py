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

import asyncio

import sqlalchemy as sa
import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation, AutomationVersion, Run, RunStep
from app.errors import Conflict, NotFound
from app.services import executor, run_events
from app.utils import LoopLocal

log = structlog.get_logger("app.runs")

ACTIVE_RUN_STATUSES = ("queued", "running")
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_STEP_STATUSES = ("pending", "running")

RESTART_ERROR = "Interrupted by server restart"

DEFAULT_RUN_LIMIT = 50
# The Activity grid pages over every automation at once, so it asks for far more rows
# per request than the per-automation run list behind the editor does.
DEFAULT_CROSS_RUN_LIMIT = 200
MAX_CROSS_RUN_LIMIT = 500
DEFAULT_KEEP_RUNS = 200

# Name of the partial unique index that enforces one active run per automation; matched
# against an `IntegrityError` so a race is reported as a 409 rather than a 500.
ACTIVE_RUN_INDEX = "runs_one_active_per_automation"

# One lock per automation, so the check-then-insert in `create_run` is atomic *within*
# this process. The database index behind it is what makes the rule hold across processes;
# the lock exists so the common case (two clicks, one worker) reports a clean 409 instead
# of relying on an integrity error, and so the loser never gets as far as writing steps.
_creation_locks: LoopLocal[dict[str, asyncio.Lock]] = LoopLocal(dict)


def creation_lock(automation_id: str) -> asyncio.Lock:
    """The lock to hold across check + insert + commit when queueing a run.

    Callers must hold it until the transaction is committed — releasing at the end of
    `create_run` would let the next waiter run its "is there an active run?" query against
    a transaction that hasn't landed yet, which is the race the lock is there to close.
    """
    locks = _creation_locks.get()
    lock = locks.get(automation_id)
    if lock is None:
        lock = locks[automation_id] = asyncio.Lock()
    return lock


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

    That rule is enforced twice. The check below is the one that produces a good error
    message, but two concurrent callers in separate transactions can both pass it, so the
    insert goes through a savepoint and a violation of the
    `runs_one_active_per_automation` partial unique index is translated into the same
    `Conflict`. Callers that can race (the `POST /runs` route, the scheduler) additionally
    hold `creation_lock(automation.id)` across the surrounding commit, which keeps the
    in-process case on the fast path.
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
    try:
        # A savepoint, so losing the race to the unique index rolls back only this insert
        # and leaves `session` usable — the caller's transaction may hold work of its own,
        # and we still need to query for the run that won.
        async with session.begin_nested():
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
            await session.flush()
    except IntegrityError as exc:
        if ACTIVE_RUN_INDEX not in str(exc.orig):
            raise
        winner = await _active_run(session, automation.id)
        log.info("run_create_lost_race", automation_id=automation.id, trigger=trigger)
        raise Conflict(
            f"Automation {automation.id} already has a "
            f"{winner.status if winner else 'queued'} run.",
            extra={"runId": winner.id if winner else None},
        ) from exc

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


def _cursor_to_datetime(before: int) -> datetime:
    """An epoch-ms `before` cursor as a UTC datetime.

    Cursors are millisecond-precision while `runs.created_at` is microsecond-precision,
    so `before` is compared with a strict `<`: handing back the `createdAt` of the last
    row of a page skips that row and everything written earlier in the same millisecond.
    That is the same trade the per-automation listing has always made — sub-millisecond
    ties are only reachable by seeding rows by hand, never by two real runs of the same
    automation (one executes at a time).
    """
    return datetime.fromtimestamp(before / 1000, tz=timezone.utc)


async def list_runs_across_automations(
    session: AsyncSession,
    *,
    limit: int = DEFAULT_CROSS_RUN_LIMIT,
    before: int | None = None,
    automation_id: str | None = None,
    statuses: list[str] | None = None,
) -> list[tuple[Run, str, int | None]]:
    """Newest-first page of runs across *every* automation.

    Returns `(run, automation_name, version_number)` triples. The name and the version
    number are joined in rather than looked up per row: the Activity grid renders a
    couple of hundred runs belonging to as many automations, and resolving either of
    those one run at a time is the N+1 this endpoint exists to avoid. The version join is
    an outer one — pruning a version sets `runs.version_id` to NULL and must not drop the
    run from the history it belongs to.
    """
    stmt = (
        select(Run, Automation.name, AutomationVersion.number)
        .join(Automation, Automation.id == Run.automation_id)
        .outerjoin(AutomationVersion, AutomationVersion.id == Run.version_id)
        .order_by(Run.created_at.desc())
        .limit(max(1, min(limit, MAX_CROSS_RUN_LIMIT)))
    )
    if automation_id is not None:
        stmt = stmt.where(Run.automation_id == automation_id)
    if statuses:
        stmt = stmt.where(Run.status.in_(statuses))
    if before is not None:
        stmt = stmt.where(Run.created_at < _cursor_to_datetime(before))
    return [(row[0], row[1], row[2]) for row in (await session.execute(stmt)).all()]


async def get_run_with_automation(
    session: AsyncSession, run_id: str
) -> tuple[Run, list[RunStep], str]:
    """One run, its steps and the name of the automation that owns it.

    The standalone counterpart of `get_run`: the Activity section reaches a run by id
    alone, without knowing (or having to fetch) which automation it belongs to.
    """
    row = (
        await session.execute(
            select(Run, Automation.name)
            .join(Automation, Automation.id == Run.automation_id)
            .where(Run.id == run_id)
        )
    ).first()
    if row is None:
        raise NotFound(f"Run {run_id} not found.")
    run, automation_name = row[0], row[1]
    steps = list(
        (
            await session.execute(
                select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.index)
            )
        )
        .scalars()
        .all()
    )
    return run, steps, automation_name


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

    Three cases, and the returned status is the honest one for each:

    - **queued** — nothing has started; it is cancelled outright here and comes back
      `cancelled`.
    - **running, owned by this process** — the executor has to unwind the step it is
      inside, so it is only signalled and comes back `running`; it reaches `cancelled`
      when the executor reports back over `run_events`.
    - **running, not owned by anything** — `request_cancel` found no task, which means the
      process that was driving it is gone. Nothing will ever finish it, so leaving it
      `running` would both lie to the client and block every future run of that automation
      (the active-run guard). It is cancelled here too, and comes back `cancelled`.

    Terminal runs are returned unchanged; cancelling twice is not an error.
    """
    run = (
        await session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFound(f"Run {run_id} not found.")

    if run.status in TERMINAL_RUN_STATUSES:
        return run.status

    # `or` short-circuits: a queued run is never signalled, and a running one is only
    # cancelled here when no task in this process answered.
    if run.status == "queued" or not executor.request_cancel(run.id):
        if run.status != "queued":
            log.warning("cancelling_unowned_run", run_id=run.id)
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

    return run.status
