"""The schedule trigger: one APScheduler job per enabled, scheduled automation.

The scheduler is a thin projection of the `automations` table. The table is the source of
truth — every write that could change an automation's schedule (`save_document`,
`set_enabled`, `delete_automation`) calls `sync_job`/`remove_job`, and `reload_all()`
rebuilds the whole job set from the table at startup, so a jobstore that is stale, empty
or thrown away entirely costs nothing but the next fire time.

That is why the jobstore choice is a soft one: jobs are persisted to Postgres so a restart
between two fires doesn't lose a misfire window, but if the jobstore can't be opened we
fall back to an in-memory one and carry on. For the same reason a scheduler that fails to
start never blocks the API from booting — manual runs, the builder and the run history all
keep working; only schedules stop firing.

Jobs reference their function by the string `"app.services.scheduler:run_scheduled"` rather
than by object, so a pickled job written by an older process still resolves after a deploy.

Overlap is prevented twice over: `max_instances=1` stops APScheduler running two instances
of the same job, and `create_run`'s "one active run per automation" check (a 409) catches
the case where a manual run is already in flight when the schedule fires.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Automation
from app.errors import Conflict
from app.services.executor import execute_run
from app.services.runs import create_run
from app.services.settings import get_timezone

log = structlog.get_logger("app.scheduler")

JOB_FUNC = "app.services.scheduler:run_scheduled"

JOB_DEFAULTS: dict[str, Any] = {
    # One run per fire: a process that was down for an hour should catch up once, not
    # sixty times.
    "coalesce": True,
    "max_instances": 1,
    # `run_scheduled` awaits the whole run, so a fire that lands while the previous one is
    # still going is dropped — the grace window only covers a brief hiccup.
    "misfire_grace_time": 60,
}

_scheduler: AsyncIOScheduler | None = None


# ─── construction ────────────────────────────────────────────────────────────────────


def sync_database_url() -> str:
    """`DATABASE_URL` with the async driver swapped for the sync one APScheduler needs.

    APScheduler 3's `SQLAlchemyJobStore` is synchronous, so it cannot use the app's asyncpg
    engine; `psycopg` (v3) talks to the same database over the same DSN.
    """
    url = get_settings().database_url
    return url.replace("+asyncpg", "+psycopg", 1)


def build_scheduler(jobstore: Any | None = None) -> AsyncIOScheduler:
    """A scheduler backed by `jobstore`, or by Postgres with an in-memory fallback."""
    if jobstore is None:
        try:
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

            jobstore = SQLAlchemyJobStore(url=sync_database_url())
        except Exception:  # noqa: BLE001 — a missing driver must not cost us schedules
            log.warning("scheduler_jobstore_unavailable", exc_info=True)
            jobstore = MemoryJobStore()
    return AsyncIOScheduler(
        jobstores={"default": jobstore}, timezone="UTC", job_defaults=JOB_DEFAULTS
    )


def get_scheduler() -> AsyncIOScheduler:
    """The process-wide scheduler, built on first use."""
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
    return _scheduler


def configure_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    """Install (or clear) the process scheduler. Test hook — see `tests/integration`."""
    global _scheduler
    _scheduler = scheduler


def _active() -> AsyncIOScheduler | None:
    """The scheduler *if one exists*, without building one.

    `sync_job` and friends are called from request handlers, including in tests and in a
    process where the scheduler never started. Building one lazily there would open a
    second connection pool to do work `reload_all()` redoes at the next startup anyway, so
    they no-op instead.
    """
    return _scheduler


# ─── lifecycle ───────────────────────────────────────────────────────────────────────


async def start() -> None:
    """Start the scheduler and rebuild its jobs from the automations table."""
    global _scheduler
    scheduler = get_scheduler()
    if not scheduler.running:
        try:
            scheduler.start()
        except Exception:  # noqa: BLE001 — most likely the jobstore's table/connection
            log.warning("scheduler_start_failed_falling_back", exc_info=True)
            scheduler = _scheduler = build_scheduler(MemoryJobStore())
            scheduler.start()
    await reload_all()
    log.info("scheduler_started", jobs=len(scheduler.get_jobs()))


async def shutdown() -> None:
    """Stop the scheduler without waiting for jobs in flight (the executor owns those)."""
    scheduler = _active()
    if scheduler is None or not scheduler.running:
        return
    scheduler.shutdown(wait=False)
    log.info("scheduler_stopped")


async def reload_all() -> None:
    """Make the job set match the table exactly: sync every automation, drop the rest."""
    scheduler = _active()
    if scheduler is None:
        return
    async with session_scope() as session:
        timezone = await get_timezone(session)
        automations = list(
            (await session.execute(select(Automation))).scalars().all()
        )
    known = set()
    for automation in automations:
        known.add(automation.id)
        sync_job(automation, timezone=timezone)
    for job in scheduler.get_jobs():
        if job.id not in known:
            remove_job(job.id)
    log.info("scheduler_reloaded", automations=len(automations))


# ─── job management ──────────────────────────────────────────────────────────────────


def _trigger_settings(document: Any) -> dict[str, Any] | None:
    """The schedule settings of `document`'s trigger, or None when it isn't a schedule.

    Reads the stored dict rather than parsing the whole `AutomationDocument`: a draft that
    doesn't validate must still be schedulable if its trigger is well formed.
    """
    if not isinstance(document, dict):
        return None
    trigger = document.get("trigger")
    if not isinstance(trigger, dict) or trigger.get("type") != "schedule":
        return None
    settings = trigger.get("settings")
    return settings if isinstance(settings, dict) else None


def _build_trigger(settings: dict[str, Any], timezone: str) -> CronTrigger | IntervalTrigger:
    tz = settings.get("timezone") or timezone or "UTC"
    if settings.get("mode") == "cron":
        return CronTrigger.from_crontab(settings["cron"], timezone=tz)
    return IntervalTrigger(minutes=int(settings["every_minutes"]), timezone=tz)


def sync_job(automation: Any, *, timezone: str = "UTC") -> None:
    """Make the job for `automation` match its document, creating or dropping as needed.

    `timezone` is the workspace fallback for a schedule that doesn't name one of its own.
    Callers inside a request usually don't have it to hand; UTC is the same default the
    settings row ships with, and `reload_all()` re-syncs with the real value at startup.
    """
    scheduler = _active()
    if scheduler is None:
        return

    settings = _trigger_settings(getattr(automation, "document", None))
    if not automation.enabled or settings is None:
        remove_job(automation.id)
        return

    try:
        trigger = _build_trigger(settings, timezone)
    except Exception:  # noqa: BLE001 — an unsaveable schedule is a draft, not a crash
        log.warning("schedule_trigger_invalid", automation_id=automation.id, exc_info=True)
        remove_job(automation.id)
        return

    scheduler.add_job(
        JOB_FUNC,
        trigger=trigger,
        id=automation.id,
        args=[automation.id],
        name=automation.name,
        replace_existing=True,
    )
    log.info("schedule_job_synced", automation_id=automation.id, trigger=str(trigger))


def remove_job(automation_id: str) -> None:
    """Drop any scheduled job for `automation_id`. Removing a job that isn't there is fine."""
    scheduler = _active()
    if scheduler is None:
        return
    try:
        scheduler.remove_job(automation_id)
    except JobLookupError:
        return
    log.info("schedule_job_removed", automation_id=automation_id)


def next_run_at(automation_id: str) -> int | None:
    """Next fire time of `automation_id`'s job as epoch ms, or None when it has none."""
    scheduler = _active()
    if scheduler is None:
        return None
    try:
        job = scheduler.get_job(automation_id)
    except Exception:  # noqa: BLE001 — a jobstore hiccup must not 500 the list view
        log.warning("schedule_next_run_failed", automation_id=automation_id, exc_info=True)
        return None
    when: datetime | None = getattr(job, "next_run_time", None) if job else None
    return int(when.timestamp() * 1000) if when is not None else None


# ─── the job itself ──────────────────────────────────────────────────────────────────


async def run_scheduled(automation_id: str) -> None:
    """Fire one scheduled run, start to finish.

    The run is *awaited* rather than handed to `start_run_in_background`: combined with
    `max_instances=1` that is what stops a slow automation on a one-minute schedule from
    stacking up runs on top of itself.
    """
    async with session_scope() as session:
        automation = await session.get(Automation, automation_id)
        if automation is None:
            log.info("run_skipped_missing_automation", automation_id=automation_id)
            remove_job(automation_id)
            return
        if not automation.enabled:
            log.info("run_skipped_disabled", automation_id=automation_id)
            return
        try:
            run = await create_run(session, automation, trigger="schedule")
        except Conflict:
            # A manual run (or a previous fire) is still going. Skipping is the right call:
            # the next tick will pick it up.
            log.info("run_skipped_overlap", automation_id=automation_id)
            return
        run_id = run.id

    await execute_run(run_id)
