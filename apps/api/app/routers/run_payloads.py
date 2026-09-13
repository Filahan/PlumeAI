"""ORM `Run`/`RunStep` rows → the API's run payloads.

Extracted from `app.routers.automations` when the cross-automation Activity endpoints
arrived: both routers hand back the *same* run shapes (`RunSummary`, `RunStepPayload`,
`RunDetail`), and a second hand-written copy of that mapping is exactly how the editor's
run drawer and the Activity grid would quietly drift apart. Nothing here touches the
request or the response — it is pure translation plus one batched lookup.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AutomationVersion, Run, RunStep
from app.schemas.automations import RunDetail, RunStepPayload, RunSummary
from app.utils import to_ms


def run_summary(run: Run, version_number: int | None) -> RunSummary:
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


def run_step(step: RunStep) -> RunStepPayload:
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


def run_detail(run: Run, steps: list[RunStep], version_number: int | None) -> RunDetail:
    return RunDetail(
        **run_summary(run, version_number).model_dump(),
        steps=[run_step(s) for s in steps],
    )


async def version_numbers(session: AsyncSession, runs: list[Run]) -> dict[str, int]:
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
