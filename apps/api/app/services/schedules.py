"""Every scheduled automation in one place: what it fires, when it fires next, and
pausing or resuming a batch of them.

This is a *read across* the automations table plus a lookup into the scheduler, which is
the only thing that knows a next fire time (`app.services.scheduler` is a projection of
the table — the table never stores one). Anything that has no job there reports
`next_run_at = None`: a paused automation, an unsaveable cron, or a process whose
scheduler failed to start.

Pausing is deliberately *not* an edit of the document. It clears `enabled`, which drops
the APScheduler job, and leaves the `schedule` trigger exactly where it was — so the
automation keeps its schedule on screen, can still be started by hand, and resuming it
restores the same fire times without touching the version history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation, Run
from app.schemas.documents import ScheduleTrigger
from app.services import automations as automations_svc
from app.services import scheduler
from app.services.documents import describe_trigger
from app.services.settings import get_timezone
from app.utils import to_ms

log = structlog.get_logger("app.schedules")

# What `trigger_summary` falls back to when the stored trigger is too malformed to
# describe. Unreachable through the API — `save_document` validates every trigger it
# writes — but a hand-edited row must not take the whole list down with it.
UNDESCRIBABLE_TRIGGER = "schedule"


@dataclass(frozen=True)
class LastRun:
    id: str
    status: str
    ended_at: int | None
    duration_ms: int | None


@dataclass(frozen=True)
class ScheduleEntry:
    """One scheduled automation, flattened for the API layer to render."""

    automation_id: str
    name: str
    enabled: bool
    trigger_summary: str
    mode: str
    cron: str | None
    every_minutes: int | None
    timezone: str | None
    next_run_at: int | None
    last_run: LastRun | None


def schedule_settings(document: Any) -> dict[str, Any] | None:
    """The `schedule` trigger settings of a stored document, or None when it has none.

    Reads the raw dict for the same reason `scheduler._trigger_settings` does: a draft
    that fails catalog validation is still scheduled, and must still be listed here.
    """
    if not isinstance(document, dict):
        return None
    trigger = document.get("trigger")
    if not isinstance(trigger, dict) or trigger.get("type") != "schedule":
        return None
    settings = trigger.get("settings")
    return settings if isinstance(settings, dict) else None


def _trigger_summary(document: dict[str, Any]) -> str:
    """`describe_trigger`'s exact phrasing for this document's trigger.

    The same sentence `GET /automations` shows — worded once, in one place, so the two
    views can never disagree about what "every weekday at 08:00" means.
    """
    try:
        return describe_trigger(ScheduleTrigger.model_validate(document.get("trigger")))
    except Exception:  # noqa: BLE001 — a broken trigger is a row, not an outage
        log.warning("schedule_trigger_undescribable", exc_info=True)
        return UNDESCRIBABLE_TRIGGER


async def _last_runs(
    session: AsyncSession, automations: list[Automation]
) -> dict[str, LastRun]:
    """`automation.id` → its most recent run, in one query for the whole list.

    `last_run_id`/`last_run_status` are denormalized onto the automation but `endedAt`
    and `durationMs` are not, so this is a single `IN` lookup over the ids already on the
    rows rather than one round trip per schedule — and is skipped entirely when nothing
    has ever run.
    """
    ids = {a.last_run_id for a in automations if a.last_run_id}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(
                Run.id, Run.automation_id, Run.status, Run.ended_at, Run.duration_ms
            ).where(Run.id.in_(ids))
        )
    ).all()
    return {
        row.automation_id: LastRun(
            id=row.id,
            status=row.status,
            ended_at=to_ms(row.ended_at) if row.ended_at else None,
            duration_ms=row.duration_ms,
        )
        for row in rows
    }


async def _scheduled_automations(
    session: AsyncSession, ids: list[str] | None = None
) -> list[Automation]:
    """Every automation whose current document carries a `schedule` trigger.

    Filtered in Python rather than with a JSONB predicate: the set is small (one row per
    automation, no joins) and the "is this a schedule?" rule already lives in exactly one
    place — `schedule_settings` — which a hand-written SQL predicate would fork.
    """
    stmt = select(Automation)
    if ids is not None:
        stmt = stmt.where(Automation.id.in_(ids))
    rows = (await session.execute(stmt)).scalars().all()
    return [a for a in rows if schedule_settings(a.document) is not None]


def _sort_key(entry: ScheduleEntry) -> tuple[int, int, str]:
    """Soonest first, never-firing last, ties broken by name.

    A paused automation has no next fire time at all, so it sorts behind every automation
    that does rather than in front of them (which is where a plain `None` would land).
    """
    if entry.next_run_at is None:
        return (1, 0, entry.name.lower())
    return (0, entry.next_run_at, entry.name.lower())


async def list_schedules(session: AsyncSession) -> tuple[str, list[ScheduleEntry]]:
    """`(workspace timezone, schedules)` — every scheduled automation, soonest first."""
    workspace_timezone = await get_timezone(session)
    automations = await _scheduled_automations(session)
    last_runs = await _last_runs(session, automations)

    entries: list[ScheduleEntry] = []
    for automation in automations:
        settings = schedule_settings(automation.document) or {}
        every_minutes = settings.get("every_minutes")
        entries.append(
            ScheduleEntry(
                automation_id=automation.id,
                name=automation.name,
                enabled=automation.enabled,
                trigger_summary=_trigger_summary(automation.document or {}),
                mode="cron" if settings.get("mode") == "cron" else "interval",
                cron=settings.get("cron"),
                every_minutes=int(every_minutes) if every_minutes is not None else None,
                # The trigger's *own* zone only. `None` means "inherits the workspace
                # one", which the caller reports alongside as the top-level `timezone`.
                timezone=settings.get("timezone"),
                next_run_at=scheduler.next_run_at(automation.id),
                last_run=last_runs.get(automation.id),
            )
        )
    entries.sort(key=_sort_key)
    return workspace_timezone, entries


async def set_schedules_enabled(
    session: AsyncSession, *, automation_ids: list[str] | None, enabled: bool
) -> list[str]:
    """Pause (`enabled=False`) or resume (`enabled=True`) scheduled automations.

    `automation_ids=None` means every scheduled automation. Ids that don't exist, or that
    name an automation without a schedule, are ignored rather than rejected: this is a
    bulk toggle over a list the client rendered a moment ago, and one automation deleted
    or switched to a manual trigger in between must not fail the other twenty.

    Returns the ids whose `enabled` actually flipped — an automation already in the
    requested state is left alone, so retrying a pause is a no-op rather than a second
    round of scheduler churn. Every flip goes through `automations.set_enabled`, which is
    what re-syncs the APScheduler job; the caller's transaction commits them together.
    """
    automations = await _scheduled_automations(session, automation_ids)
    changed: list[str] = []
    for automation in automations:
        if automation.enabled == enabled:
            continue
        await automations_svc.set_enabled(session, automation, enabled)
        changed.append(automation.id)
    log.info("schedules_toggled", enabled=enabled, changed=len(changed))
    return changed
