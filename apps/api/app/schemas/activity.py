"""Request/response shapes for the cross-automation `/runs` and `/schedules` API.

Same conventions as `app.schemas.automations`: camelCase JSON (`APISchema`) and epoch
milliseconds for every timestamp. The run payloads deliberately *extend* `RunSummary` /
`RunDetail` rather than redeclaring their fields, so the Activity section and the
per-automation editor views stay one shape — a run row gains `automationName` and
nothing else.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.automations import RunDetail, RunStatus, RunSummary
from app.schemas.base import APISchema

ScheduleMode = Literal["cron", "interval"]


# --- runs --------------------------------------------------------------------------------


class RunListItem(RunSummary):
    """A run as it appears in the cross-automation grid: `RunSummary` + the name of the
    automation it belongs to (`automationId` is already on `RunSummary`)."""

    automation_name: str


class RunListResponse(APISchema):
    """A page of runs, newest first.

    `nextCursor` is the `createdAt` of the last row, to be handed back as `before`; it is
    `null` when the page was not full, which is the only "there is no more" signal the
    client needs.
    """

    runs: list[RunListItem] = Field(default_factory=list)
    next_cursor: int | None = None


class RunDetailWithAutomation(RunDetail):
    """One run and its steps, plus the name of the automation that owns it.

    `automationId` comes from `RunSummary`; only the name has to be added here, and it is
    what lets the Activity drawer title a run without a second request.
    """

    automation_name: str


# --- schedules ---------------------------------------------------------------------------


class ScheduleLastRun(APISchema):
    """The automation's most recent run. `endedAt`/`durationMs` are null while it is
    still queued or running."""

    id: str
    status: RunStatus
    ended_at: int | None = None
    duration_ms: int | None = None


class ScheduleItem(APISchema):
    """One scheduled automation: what it is set to do, and when it will next do it.

    `triggerSummary` is `describe_trigger`'s phrasing verbatim — the same sentence the
    automations list shows, so the two views never word a schedule differently.
    `timezone` is the *trigger's* own zone, or null when it inherits the workspace one
    (`SchedulesResponse.timezone`). `nextRunAt` is null when the scheduler holds no job
    for this automation: it is paused, or the scheduler never started.
    """

    automation_id: str
    name: str
    enabled: bool
    trigger_summary: str
    mode: ScheduleMode
    cron: str | None = None
    every_minutes: int | None = None
    timezone: str | None = None
    next_run_at: int | None = None
    last_run: ScheduleLastRun | None = None


class SchedulesResponse(APISchema):
    """Every scheduled automation, plus the workspace timezone they resolve against."""

    timezone: str
    schedules: list[ScheduleItem] = Field(default_factory=list)


class SchedulesToggleRequest(APISchema):
    """Which automations to pause or resume. `null` (or omitted) means all of them."""

    automation_ids: list[str] | None = None


class SchedulesToggleResponse(APISchema):
    """What actually changed: ids whose `enabled` flipped, and how many that was.

    An automation that was already in the requested state is not listed — pausing twice
    reports `changed: 0`, which is what makes the endpoint safe to retry.
    """

    changed: int
    automation_ids: list[str] = Field(default_factory=list)
