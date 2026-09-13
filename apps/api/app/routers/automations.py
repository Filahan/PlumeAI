"""The `/automations` API: automation CRUD, document editing, version history and runs.

Reading a document is always a *fresh* validation against the live catalog, never the
`issues` that happened to be true when it was saved — an integration disconnected since
the last edit has to show up as a problem the next time the builder opens the
automation, not the next time somebody edits it.

Writes all funnel through `app.services.automations.save_document`, which decides
whether the edit is worth a new version. Runs are created here but executed elsewhere:
`POST /{id}/runs` persists a `queued` run and hands the id to
`app.services.executor.start_run_in_background`, which is a no-op seam until Task 4b.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentUser
from app.db.base import get_session
from app.db.models import Automation, AutomationVersion, Run, RunStep
from app.errors import NotFound
from app.schemas.automations import (
    AutomationDetail,
    AutomationSummary,
    CancelRunResponse,
    CreateAutomationRequest,
    LastRunPayload,
    OperationsRequest,
    OperationsResponse,
    PatchAutomationRequest,
    ReplaceDocumentRequest,
    RunDetail,
    RunStepPayload,
    RunSummary,
    StartRunRequest,
    StartRunResponse,
    ValidateRequest,
    ValidateResponse,
    VersionDetail,
    VersionSummary,
)
from app.schemas.documents import AutomationDocument
from app.services import automations as svc
from app.services import executor, run_events, scheduler
from app.services import runs as runs_svc
from app.services.documents import describe_trigger, diff_summary, dump_document
from app.utils import to_ms

router = APIRouter(prefix="/automations", tags=["automations"])
log = structlog.get_logger("app.automations")

DBSession = Annotated[AsyncSession, Depends(get_session)]

# Events the executor publishes carry a `type`; this one means "stop reading".
RUN_FINISHED_EVENT = "run_finished"


# ─── payload builders ────────────────────────────────────────────────────────────────


def _sse(event: dict[str, Any]) -> dict[str, str]:
    return {"data": json.dumps(event, separators=(",", ":"), default=str)}


async def _last_runs(
    session: AsyncSession, automations: list[Automation]
) -> dict[str, LastRunPayload]:
    """`automation.id` → its last run, resolved in one query for the whole page.

    `last_run_status` is denormalized onto the automation, but `endedAt` isn't — so this
    adds a single `IN` lookup for the whole page rather than one round trip per row, and
    is skipped entirely when no listed automation has ever run.
    """
    ids = {a.last_run_id for a in automations if a.last_run_id and a.last_run_status}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Run.id, Run.automation_id, Run.status, Run.ended_at).where(Run.id.in_(ids))
        )
    ).all()
    return {
        row.automation_id: LastRunPayload(
            status=row.status, ended_at=to_ms(row.ended_at) if row.ended_at else None
        )
        for row in rows
    }


def _summary(
    automation: Automation, last_run: LastRunPayload | None
) -> AutomationSummary:
    document = automation.document or {}
    trigger_summary = "manual trigger"
    try:
        trigger_summary = describe_trigger(
            AutomationDocument.model_validate(document).trigger
        )
    except Exception:  # noqa: BLE001 — a broken draft must not break the whole list
        log.warning("automation_trigger_undescribable", automation_id=automation.id)
    return AutomationSummary(
        id=automation.id,
        name=automation.name,
        enabled=automation.enabled,
        trigger_summary=trigger_summary,
        next_run_at=scheduler.next_run_at(automation.id),
        last_run=last_run,
        valid=automation.valid,
        updated_at=to_ms(automation.updated_at),
    )


async def _detail(session: AsyncSession, automation: Automation) -> AutomationDetail:
    """Re-validate the stored draft so `issues` reflect the catalog as it is right now."""
    document = automation.document or {}
    issues: list[Any] = []
    try:
        parsed = AutomationDocument.model_validate(document)
    except Exception:  # noqa: BLE001 — show the raw draft rather than 500ing on it
        log.warning("automation_document_unparseable", automation_id=automation.id)
    else:
        validated, issues = await svc.validate_draft(session, parsed)
        document = dump_document(validated)

    last_runs = await _last_runs(session, [automation])
    return AutomationDetail(
        id=automation.id,
        name=automation.name,
        enabled=automation.enabled,
        document=document,
        version_number=await svc.current_version_number(session, automation),
        issues=issues,
        next_run_at=scheduler.next_run_at(automation.id),
        assistant_messages=list(automation.assistant_messages or []),
        last_run=last_runs.get(automation.id),
        created_at=to_ms(automation.created_at),
        updated_at=to_ms(automation.updated_at),
    )


def _version_summary(version: AutomationVersion) -> VersionSummary:
    return VersionSummary(
        number=version.number,
        created_by=version.created_by,  # type: ignore[arg-type]
        created_at=to_ms(version.created_at),
    )


def _run_summary(run: Run, version_number: int | None) -> RunSummary:
    return RunSummary(
        id=run.id,
        automation_id=run.automation_id,
        version_number=version_number,
        trigger=run.trigger,  # type: ignore[arg-type]
        status=run.status,  # type: ignore[arg-type]
        stopped_by_step_id=run.stopped_by_step_id,
        error=run.error,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        started_at=to_ms(run.started_at) if run.started_at else None,
        ended_at=to_ms(run.ended_at) if run.ended_at else None,
        duration_ms=run.duration_ms,
        created_at=to_ms(run.created_at),
    )


def _run_step(step: RunStep) -> RunStepPayload:
    return RunStepPayload(
        id=step.id,
        step_id=step.step_id,
        index=step.index,
        name=step.name,
        type=step.type,
        status=step.status,  # type: ignore[arg-type]
        attempt=step.attempt,
        resolved_input=step.resolved_input,
        output=step.output,
        error=step.error,
        trace=list(step.trace or []),
        started_at=to_ms(step.started_at) if step.started_at else None,
        ended_at=to_ms(step.ended_at) if step.ended_at else None,
        duration_ms=step.duration_ms,
    )


def _run_detail(run: Run, steps: list[RunStep], version_number: int | None) -> RunDetail:
    return RunDetail(
        **_run_summary(run, version_number).model_dump(),
        steps=[_run_step(s) for s in steps],
    )


async def _version_numbers(session: AsyncSession, runs: list[Run]) -> dict[str, int]:
    """`version_id` → `number` for the versions referenced by `runs` (one query)."""
    ids = {r.version_id for r in runs if r.version_id}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AutomationVersion.id, AutomationVersion.number).where(
                AutomationVersion.id.in_(ids)
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def _diff_from_raw(old_raw: dict[str, Any], new: AutomationDocument) -> list[str]:
    """Diff a raw stored document against a freshly saved one, for the PUT summary."""
    return diff_summary(AutomationDocument.model_validate(old_raw), new)


async def _run_in_automation(
    session: AsyncSession, automation_id: str, run_id: str
) -> tuple[Run, list[RunStep]]:
    run, steps = await runs_svc.get_run(session, run_id)
    if run.automation_id != automation_id:
        raise NotFound(f"Run {run_id} not found.")
    return run, steps


# ─── automations ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[AutomationSummary], response_model_by_alias=True)
async def list_automations_route(
    user: CurrentUser, session: DBSession
) -> list[AutomationSummary]:
    automations = await svc.list_automations(session)
    last_runs = await _last_runs(session, automations)
    return [_summary(a, last_runs.get(a.id)) for a in automations]


@router.post(
    "",
    response_model=AutomationDetail,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_automation_route(
    body: CreateAutomationRequest, user: CurrentUser, session: DBSession
) -> AutomationDetail:
    automation = await svc.create_automation(
        session, name=body.name, document=body.document
    )
    return await _detail(session, automation)


@router.post("/validate", response_model=ValidateResponse, response_model_by_alias=True)
async def validate_route(
    body: ValidateRequest, user: CurrentUser, session: DBSession
) -> ValidateResponse:
    """Dry run: validate a document the client is editing without touching the database.

    Declared before the `/{automation_id}` routes so "validate" is never read as an id.
    """
    doc = svc.parse_document(body.document)
    validated, issues = await svc.validate_draft(session, doc)
    return ValidateResponse(document=dump_document(validated), issues=issues)


@router.get("/{automation_id}", response_model=AutomationDetail, response_model_by_alias=True)
async def get_automation_route(
    automation_id: str, user: CurrentUser, session: DBSession
) -> AutomationDetail:
    automation = await svc.get_automation(session, automation_id)
    return await _detail(session, automation)


@router.put(
    "/{automation_id}", response_model=OperationsResponse, response_model_by_alias=True
)
async def replace_document_route(
    automation_id: str,
    body: ReplaceDocumentRequest,
    user: CurrentUser,
    session: DBSession,
) -> OperationsResponse:
    """Whole-document replace, as written by the JSON editor. Unlike every other write,
    a document that isn't a well-formed `AutomationDocument` is rejected (422)."""
    automation = await svc.get_automation(session, automation_id)
    old = automation.document or {}
    validated, issues, number = await svc.save_document(
        session, automation, body.document, created_by="json"
    )
    summary: list[str] = []
    try:
        summary = _diff_from_raw(old, validated)
    except Exception:  # noqa: BLE001 — a previously-unparseable draft has no diff to show
        summary = []
    return OperationsResponse(
        document=dump_document(validated),
        issues=issues,
        version_number=number,
        summary=summary,
    )


@router.patch(
    "/{automation_id}", response_model=AutomationDetail, response_model_by_alias=True
)
async def patch_automation_route(
    automation_id: str,
    body: PatchAutomationRequest,
    user: CurrentUser,
    session: DBSession,
) -> AutomationDetail:
    automation = await svc.get_automation(session, automation_id)
    if body.name is not None:
        await svc.rename(session, automation, body.name)
    if body.enabled is not None:
        await svc.set_enabled(session, automation, body.enabled)
    return await _detail(session, automation)


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_route(
    automation_id: str, user: CurrentUser, session: DBSession
) -> Response:
    automation = await svc.get_automation(session, automation_id)
    await svc.delete_automation(session, automation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── document editing ────────────────────────────────────────────────────────────────


@router.post(
    "/{automation_id}/operations",
    response_model=OperationsResponse,
    response_model_by_alias=True,
)
async def apply_operations_route(
    automation_id: str, body: OperationsRequest, user: CurrentUser, session: DBSession
) -> OperationsResponse:
    automation = await svc.get_automation(session, automation_id)
    validated, issues, number, summary = await svc.apply_ops(
        session, automation, body.operations, created_by="user"
    )
    return OperationsResponse(
        document=dump_document(validated),
        issues=issues,
        version_number=number,
        summary=summary,
    )


# ─── versions ────────────────────────────────────────────────────────────────────────


@router.get(
    "/{automation_id}/versions",
    response_model=list[VersionSummary],
    response_model_by_alias=True,
)
async def list_versions_route(
    automation_id: str, user: CurrentUser, session: DBSession
) -> list[VersionSummary]:
    await svc.get_automation(session, automation_id)
    return [_version_summary(v) for v in await svc.list_versions(session, automation_id)]


@router.get(
    "/{automation_id}/versions/{number}",
    response_model=VersionDetail,
    response_model_by_alias=True,
)
async def get_version_route(
    automation_id: str, number: int, user: CurrentUser, session: DBSession
) -> VersionDetail:
    await svc.get_automation(session, automation_id)
    version = await svc.get_version(session, automation_id, number)
    return VersionDetail(
        number=version.number,
        created_by=version.created_by,  # type: ignore[arg-type]
        created_at=to_ms(version.created_at),
        document=version.document,
    )


@router.post(
    "/{automation_id}/versions/{number}/restore",
    response_model=OperationsResponse,
    response_model_by_alias=True,
)
async def restore_version_route(
    automation_id: str, number: int, user: CurrentUser, session: DBSession
) -> OperationsResponse:
    automation = await svc.get_automation(session, automation_id)
    validated, issues, new_number, summary = await svc.restore_version(
        session, automation, number
    )
    return OperationsResponse(
        document=dump_document(validated),
        issues=issues,
        version_number=new_number,
        summary=summary,
    )


# ─── runs ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{automation_id}/runs",
    response_model=StartRunResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run_route(
    automation_id: str, body: StartRunRequest, user: CurrentUser, session: DBSession
) -> StartRunResponse:
    """Queue a run and hand it to the executor. 409 when one is already in flight."""
    automation = await svc.get_automation(session, automation_id)
    # Held across the commit, not just the insert: two simultaneous clicks would otherwise
    # both find no active run and both be queued. See `runs_svc.creation_lock`.
    async with runs_svc.creation_lock(automation_id):
        run = await runs_svc.create_run(session, automation, trigger=body.trigger)
        # Committed here rather than by the dependency so the background executor, which
        # opens its own session, can actually see the run it's about to be handed.
        await session.commit()
        run_id = run.id
    executor.start_run_in_background(run_id)
    return StartRunResponse(run_id=run_id)


@router.get(
    "/{automation_id}/runs", response_model=list[RunSummary], response_model_by_alias=True
)
async def list_runs_route(
    automation_id: str,
    user: CurrentUser,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=200)] = runs_svc.DEFAULT_RUN_LIMIT,
    before: Annotated[int | None, Query(description="createdAt cursor, epoch ms")] = None,
) -> list[RunSummary]:
    await svc.get_automation(session, automation_id)
    runs = await runs_svc.list_runs(session, automation_id, limit=limit, before=before)
    numbers = await _version_numbers(session, runs)
    return [_run_summary(r, numbers.get(r.version_id or "")) for r in runs]


@router.get(
    "/{automation_id}/runs/{run_id}", response_model=RunDetail, response_model_by_alias=True
)
async def get_run_route(
    automation_id: str, run_id: str, user: CurrentUser, session: DBSession
) -> RunDetail:
    run, steps = await _run_in_automation(session, automation_id, run_id)
    numbers = await _version_numbers(session, [run])
    return _run_detail(run, steps, numbers.get(run.version_id or ""))


@router.post(
    "/{automation_id}/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    response_model_by_alias=True,
)
async def cancel_run_route(
    automation_id: str, run_id: str, user: CurrentUser, session: DBSession
) -> CancelRunResponse:
    await _run_in_automation(session, automation_id, run_id)
    status_after = await runs_svc.cancel_run(session, run_id)
    return CancelRunResponse(status=status_after)  # type: ignore[arg-type]


@router.get("/{automation_id}/runs/{run_id}/events")
async def run_events_route(
    automation_id: str, run_id: str, user: CurrentUser, session: DBSession
) -> EventSourceResponse:
    """Live progress for one run.

    Always opens with a `snapshot` built from the database, so a client that connects
    late (or reconnects) starts from the authoritative state rather than from whatever
    happens to be published next. A run that has already finished gets the snapshot and
    an immediate end-of-stream.
    """
    run, steps = await _run_in_automation(session, automation_id, run_id)
    numbers = await _version_numbers(session, [run])
    snapshot = _run_detail(run, steps, numbers.get(run.version_id or ""))
    finished = run.status in runs_svc.TERMINAL_RUN_STATUSES

    # Subscribe before yielding the snapshot: anything the executor publishes while the
    # snapshot is being serialized is then queued rather than lost.
    queue = run_events.subscribe(run_id)

    async def generator() -> AsyncIterator[dict[str, str]]:
        try:
            yield _sse({"type": "snapshot", "run": snapshot.model_dump(by_alias=True)})
            if finished:
                return
            while True:
                item = await queue.get()
                if item is run_events.SENTINEL:
                    break
                yield _sse(item)
                if item.get("type") == RUN_FINISHED_EVENT:
                    break
        finally:
            run_events.unsubscribe(run_id, queue)

    return EventSourceResponse(generator())
