"""The Activity API: runs and schedules read *across* every automation.

The per-automation endpoints in `app.routers.automations` answer "what has this one
automation been doing?" — they are what the editor uses and they are unchanged. These
answer the monitoring question instead: one grid of every run in the workspace, one list
of every schedule with its next fire time, and a bulk pause/resume over those schedules.

Both list endpoints are written to hold a *bounded* number of queries no matter how many
rows come back — the automation name and version number of a run are joined in
(`runs.list_runs_across_automations`), and a schedule's last run is one batched `IN`
lookup — because the whole point of this section is showing a few hundred rows at once.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.base import get_session
from app.routers.run_payloads import run_detail, run_summary, version_numbers
from app.schemas.activity import (
    RunDetailWithAutomation,
    RunListItem,
    RunListResponse,
    ScheduleItem,
    ScheduleLastRun,
    SchedulesResponse,
    SchedulesToggleRequest,
    SchedulesToggleResponse,
)
from app.schemas.automations import RunStatus
from app.services import runs as runs_svc
from app.services import schedules as schedules_svc
from app.utils import to_ms

router = APIRouter(tags=["activity"])

DBSession = Annotated[AsyncSession, Depends(get_session)]


# ─── runs ────────────────────────────────────────────────────────────────────────────


@router.get("/runs", response_model=RunListResponse, response_model_by_alias=True)
async def list_runs_route(
    user: CurrentUser,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=runs_svc.MAX_CROSS_RUN_LIMIT)] = (
        runs_svc.DEFAULT_CROSS_RUN_LIMIT
    ),
    before: Annotated[int | None, Query(description="createdAt cursor, epoch ms")] = None,
    automation_id: Annotated[
        str | None, Query(alias="automationId", description="Only this automation's runs")
    ] = None,
    status: Annotated[
        list[RunStatus] | None, Query(description="Repeatable; any of these statuses")
    ] = None,
) -> RunListResponse:
    """Recent runs across every automation, newest first.

    `nextCursor` is set only when the page came back full — hand it straight back as
    `before` for the next page. A short page means there is nothing older to fetch, so
    the client never has to make a request that returns an empty list to find that out.
    """
    rows = await runs_svc.list_runs_across_automations(
        session, limit=limit, before=before, automation_id=automation_id, statuses=status
    )
    runs = [
        RunListItem(
            **run_summary(run, version_number).model_dump(), automation_name=automation_name
        )
        for run, automation_name, version_number in rows
    ]
    next_cursor = to_ms(rows[-1][0].created_at) if len(rows) == limit else None
    return RunListResponse(runs=runs, next_cursor=next_cursor)


@router.get(
    "/runs/{run_id}", response_model=RunDetailWithAutomation, response_model_by_alias=True
)
async def get_run_route(
    run_id: str, user: CurrentUser, session: DBSession
) -> RunDetailWithAutomation:
    """One run and its steps, addressed by id alone.

    The nested `GET /automations/{id}/runs/{run_id}` returns the same run; this exists so
    the Activity grid — which has a run id and nothing else — can open it without first
    resolving which automation it belongs to.
    """
    run, steps, automation_name = await runs_svc.get_run_with_automation(session, run_id)
    numbers = await version_numbers(session, [run])
    return RunDetailWithAutomation(
        **run_detail(run, steps, numbers.get(run.version_id or "")).model_dump(),
        automation_name=automation_name,
    )


# ─── schedules ───────────────────────────────────────────────────────────────────────


@router.get("/schedules", response_model=SchedulesResponse, response_model_by_alias=True)
async def list_schedules_route(user: CurrentUser, session: DBSession) -> SchedulesResponse:
    """Every automation that fires on a schedule, soonest first (never-firing last).

    The top-level `timezone` is the workspace one every schedule resolves against; a
    schedule's own `timezone` is set only when its trigger names one, and `null` means it
    inherits. `nextRunAt` is the scheduler's answer, so it is `null` for a paused
    automation and for every automation when the scheduler could not start.
    """
    workspace_timezone, entries = await schedules_svc.list_schedules(session)
    return SchedulesResponse(
        timezone=workspace_timezone,
        schedules=[
            ScheduleItem(
                automation_id=entry.automation_id,
                name=entry.name,
                enabled=entry.enabled,
                trigger_summary=entry.trigger_summary,
                mode=entry.mode,  # type: ignore[arg-type]
                cron=entry.cron,
                every_minutes=entry.every_minutes,
                timezone=entry.timezone,
                next_run_at=entry.next_run_at,
                last_run=(
                    ScheduleLastRun(
                        id=entry.last_run.id,
                        status=entry.last_run.status,  # type: ignore[arg-type]
                        ended_at=entry.last_run.ended_at,
                        duration_ms=entry.last_run.duration_ms,
                    )
                    if entry.last_run
                    else None
                ),
            )
            for entry in entries
        ],
    )


@router.post(
    "/schedules/pause", response_model=SchedulesToggleResponse, response_model_by_alias=True
)
async def pause_schedules_route(
    body: SchedulesToggleRequest, user: CurrentUser, session: DBSession
) -> SchedulesToggleResponse:
    """Stop the given schedules from firing (`automationIds: null` pauses all of them).

    Pausing only clears `enabled`, which drops the automation's scheduler job. The
    `schedule` trigger stays in the document untouched — the automation still shows its
    schedule, can still be started by hand with `POST /automations/{id}/runs`, and
    resuming it brings the same fire times back without writing a new version.
    """
    changed = await schedules_svc.set_schedules_enabled(
        session, automation_ids=body.automation_ids, enabled=False
    )
    return SchedulesToggleResponse(changed=len(changed), automation_ids=changed)


@router.post(
    "/schedules/resume", response_model=SchedulesToggleResponse, response_model_by_alias=True
)
async def resume_schedules_route(
    body: SchedulesToggleRequest, user: CurrentUser, session: DBSession
) -> SchedulesToggleResponse:
    """Let the given schedules fire again (`automationIds: null` resumes all of them).

    The exact inverse of `/schedules/pause`: it sets `enabled` and re-syncs the scheduler
    job, and because pausing never touched the document there is nothing to restore.
    """
    changed = await schedules_svc.set_schedules_enabled(
        session, automation_ids=body.automation_ids, enabled=True
    )
    return SchedulesToggleResponse(changed=len(changed), automation_ids=changed)
