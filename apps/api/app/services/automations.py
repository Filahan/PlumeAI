"""CRUD for tasks — list, create, partial update, delete."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task as TaskRow
from app.errors import NotFound
from app.schemas.automations import (
    CreateTaskRequest,
    InterviewMessage,
    TaskPayload,
    TaskRun,
    UpdateTaskRequest,
)
from app.utils import to_ms as _dt_ms


def _row_to_task(r: TaskRow) -> TaskPayload:
    return TaskPayload(
        id=r.id,
        title=r.title,
        prompt=r.prompt,
        messages=[InterviewMessage.model_validate(m) for m in (r.messages or [])],
        schedule=r.schedule,  # type: ignore[arg-type]
        status=r.status,  # type: ignore[arg-type]
        output=r.output,
        transcript=list(r.transcript or []),
        runs=[TaskRun.model_validate(rr) for rr in (r.runs or [])],
        provider=r.provider,
        model=r.model,
        error=r.error,
        created_at=_dt_ms(r.created_at),
        updated_at=_dt_ms(r.updated_at),
    )


async def list_tasks(session: AsyncSession) -> list[TaskPayload]:
    rows = (
        await session.execute(select(TaskRow).order_by(TaskRow.created_at.desc()))
    ).scalars().all()
    return [_row_to_task(r) for r in rows]


async def get_task(session: AsyncSession, task_id: str) -> TaskRow:
    row = (
        await session.execute(select(TaskRow).where(TaskRow.id == task_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Task {task_id} not found.")
    return row


async def create_task(session: AsyncSession, req: CreateTaskRequest) -> TaskPayload:
    row = TaskRow(
        id=req.id,
        prompt=req.prompt,
        messages=[],
        schedule=req.schedule,
        status="idle",
        transcript=[],
        runs=[],
        provider=req.provider,
        model=req.model,
    )
    session.add(row)
    await session.flush()
    return _row_to_task(row)


async def update_task(
    session: AsyncSession, task_id: str, patch: UpdateTaskRequest
) -> TaskPayload:
    row = await get_task(session, task_id)
    data = patch.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _row_to_task(row)


async def delete_task(session: AsyncSession, task_id: str) -> None:
    await session.execute(delete(TaskRow).where(TaskRow.id == task_id))


# ─── Helpers used by interview + run services ──────────────────────────────────────

async def append_messages(
    session: AsyncSession,
    task_id: str,
    new_messages: list[dict[str, Any]],
    *,
    prompt: str | None = None,
    title: str | None = None,
) -> None:
    """Append `new_messages` to the task's history, optionally also setting prompt/title."""
    row = await get_task(session, task_id)
    row.messages = list(row.messages or []) + new_messages
    if prompt is not None:
        row.prompt = prompt
    if title is not None and not row.title:
        row.title = title
    row.updated_at = datetime.now(timezone.utc)


async def append_run(
    session: AsyncSession,
    task_id: str,
    *,
    run: TaskRun,
    output: str,
    transcript: list[dict[str, Any]],
    status: str,
    error: str | None,
    max_runs: int = 30,
) -> None:
    row = await get_task(session, task_id)
    runs = list(row.runs or [])
    runs.append(run.model_dump(by_alias=True))
    row.runs = runs[-max_runs:]
    row.status = status  # type: ignore[assignment]
    row.output = output
    row.transcript = transcript
    row.error = error
    row.updated_at = datetime.now(timezone.utc)
