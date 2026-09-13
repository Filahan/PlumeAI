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

import asyncio
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
from app.services.executor import start_run_in_background
from app.services.runs import create_run, creation_lock
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
        # Plain rows, not ORM objects: the session closes at the end of this block, and an
        # `Automation` instance read out of it would lazy-load (and fail) the moment
        # `sync_job` touched an attribute below.
        rows = list(
            (
                await session.execute(
                    select(
                        Automation.id,
                        Automation.name,
                        Automation.enabled,
                        Automation.document,
                    )
                )
            ).all()
        )
    known = {row.id for row in rows}
    for row in rows:
        sync_job(row, timezone=timezone)
    for job in scheduler.get_jobs():
        if job.id not in known:
            remove_job(job.id)
    log.info("scheduler_reloaded", automations=len(rows))


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


# Standard cron numbers the weekdays from Sunday (0 or 7 = Sunday, 1 = Monday), and that
# is the convention the whole product speaks: `croniter` validates with it, the trigger
# form writes it, and `describe_trigger` reads `1-5` back as "weekdays". APScheduler
# numbers them from Monday instead, so handing it a raw crontab shifts every
# day-constrained schedule one day late — `0 8 * * 1-5` would fire Tuesday to Saturday.
# `_cron_days_to_apscheduler` translates the field into APScheduler's day *names*, which
# mean the same thing under either numbering.
_CRON_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_CRON_DAY_NUMBERS = {name: index for index, name in enumerate(_CRON_DAY_NAMES)}
# APScheduler orders its week Monday-first; emitting the field in that order keeps the
# expression readable in a job listing.
_APSCHEDULER_DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _cron_day_number(token: str) -> int:
    """One day of the week, as a standard-cron number (0 = Sunday), from a number or name."""
    token = token.strip().lower()
    if token in _CRON_DAY_NUMBERS:
        return _CRON_DAY_NUMBERS[token]
    number = int(token)
    if not 0 <= number <= 7:
        raise ValueError(f"day of week out of range: {token!r}")
    # Both 0 and 7 mean Sunday in standard cron.
    return 0 if number == 7 else number


def _cron_days_to_apscheduler(field: str) -> str:
    """Rewrite a standard-cron day-of-week field as a list of APScheduler day names.

    Raises `ValueError` on anything it cannot read, which `_build_trigger` turns back into
    the original crontab so a schedule it doesn't understand still reaches APScheduler.
    """
    field = field.strip()
    if field in ("*", "?", ""):
        return "*"

    days: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            step = int(step_text)
            if step < 1:
                raise ValueError(f"step must be positive: {field!r}")
            part = part.strip()

        if part in ("*", "?", ""):
            first, last = 0, 6
        elif "-" in part[1:]:
            # `part[1:]` so a leading '-' is a malformed token, not a range separator.
            first_text, _, last_text = part.partition("-")
            first, last = _cron_day_number(first_text), _cron_day_number(last_text)
            if first > last:
                # Standard cron wraps `5-1` around the weekend; APScheduler's ranges do
                # not, and guessing would be worse than declining.
                raise ValueError(f"wrapping day range is not supported: {part!r}")
        else:
            first = last = _cron_day_number(part)

        days.update(range(first, last + 1, step))

    if not days:
        raise ValueError(f"day of week matches nothing: {field!r}")
    if len(days) == 7:
        return "*"
    names = {_CRON_DAY_NAMES[day] for day in days}
    return ",".join(name for name in _APSCHEDULER_DAY_ORDER if name in names)


def _cron_trigger(expression: str, tz: str) -> CronTrigger:
    """A `CronTrigger` reading `expression` the way standard cron does."""
    fields = expression.split()
    if len(fields) != 5:
        return CronTrigger.from_crontab(expression, timezone=tz)
    minute, hour, day, month, day_of_week = fields
    try:
        day_of_week = _cron_days_to_apscheduler(day_of_week)
    except ValueError:
        # An unreadable day field is APScheduler's to reject, with its own message.
        return CronTrigger.from_crontab(expression, timezone=tz)
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=tz,
    )


def _build_trigger(settings: dict[str, Any], timezone: str) -> CronTrigger | IntervalTrigger:
    tz = settings.get("timezone") or timezone or "UTC"
    if settings.get("mode") == "cron":
        return _cron_trigger(settings["cron"], tz)
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

    The run is started as a normal background task and then *awaited*: awaiting it is what,
    together with `max_instances=1`, stops a slow automation on a one-minute schedule from
    stacking runs on top of itself, while going through `start_run_in_background` keeps the
    run in `executor.RUNNING_TASKS` — so it can be cancelled through the API and is cleaned
    up by `cancel_all` at shutdown, exactly like a manual one.
    """
    # APScheduler's timer callbacks inherit the context of whatever added the job — often
    # the HTTP request that saved the schedule — so a scheduled run would otherwise log a
    # stale `request_id`/`path` for the lifetime of the process.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(automation_id=automation_id, trigger="schedule")
    async with session_scope() as session:
        automation = await session.get(Automation, automation_id)
        if automation is None:
            log.info("run_skipped_missing_automation", automation_id=automation_id)
            remove_job(automation_id)
            return
        if not automation.enabled:
            log.info("run_skipped_disabled", automation_id=automation_id)
            return
        # Same lock the `POST /runs` route holds, so a fire landing at the same moment as
        # a manual start is serialized rather than relying on the unique index to reject it.
        async with creation_lock(automation_id):
            try:
                run = await create_run(session, automation, trigger="schedule")
            except Conflict:
                # A manual run (or a previous fire) is still going. Skipping is the right
                # call: the next tick will pick it up.
                log.info("run_skipped_overlap", automation_id=automation_id)
                return
            await session.commit()
            run_id = run.id

    # `asyncio.wait` rather than `await task`: the executor handles its own cancellation
    # and ends cleanly, but a shutdown that cancels *this* job mid-wait should not surface
    # as an unhandled error out of an APScheduler job.
    await asyncio.wait({start_run_in_background(run_id)})
