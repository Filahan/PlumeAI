"""`app.services.runs` — snapshot semantics, restart recovery and pruning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Run, RunStep
from app.errors import Conflict
from app.services import automations as svc
from app.services import run_events
from app.services import runs as runs_svc


@pytest.fixture
def automation_factory(session, make_document):
    """Create a persisted automation whose document holds `steps`."""

    async def build(steps: list[dict] | None = None):
        automation = await svc.create_automation(
            session, document=make_document("Demo", steps if steps is not None else [])
        )
        await session.flush()
        return automation

    return build


# --- create_run ---------------------------------------------------------------------------


async def test_create_run_snapshots_the_current_version(
    session,
    automation_factory,
    ai_step,
) -> None:
    automation = await automation_factory([ai_step("step_aaaaa"), ai_step("step_bbbbb")])
    version_id = automation.current_version_id

    run = await runs_svc.create_run(session, automation, trigger="manual")

    assert run.status == "queued"
    assert run.version_id == version_id
    assert run.trigger == "manual"
    assert automation.last_run_id == run.id
    assert automation.last_run_status == "queued"

    steps = (
        (
            await session.execute(
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.index)
            )
        )
        .scalars()
        .all()
    )
    assert [s.step_id for s in steps] == ["step_aaaaa", "step_bbbbb"]
    assert [s.index for s in steps] == [0, 1]
    assert {s.status for s in steps} == {"pending"}
    assert {s.type for s in steps} == {"ai"}
    assert all(s.attempt == 0 and s.trace == [] for s in steps)


async def test_editing_the_document_does_not_change_a_run_in_flight(
    session,
    automation_factory,
    ai_step,
    make_document,
) -> None:
    """The whole point of pinning `version_id`: a run executes the document as it was."""
    automation = await automation_factory([ai_step("step_aaaaa")])
    run = await runs_svc.create_run(session, automation, trigger="manual")
    pinned_version = run.version_id

    await svc.save_document(
        session,
        automation,
        make_document("Demo", [ai_step("step_aaaaa"), ai_step("step_ccccc")]),
        created_by="user",
    )

    _, steps = await runs_svc.get_run(session, run.id)
    assert run.version_id == pinned_version
    assert automation.current_version_id != pinned_version
    assert [s.step_id for s in steps] == ["step_aaaaa"]


async def test_create_run_conflicts_with_an_active_run(
    session,
    automation_factory,
    ai_step,
) -> None:
    automation = await automation_factory([ai_step("step_aaaaa")])
    first = await runs_svc.create_run(session, automation, trigger="manual")

    with pytest.raises(Conflict) as exc:
        await runs_svc.create_run(session, automation, trigger="manual")
    assert exc.value.extra["runId"] == first.id

    # A terminal run frees the slot again.
    first.status = "succeeded"
    await session.flush()
    assert await runs_svc.create_run(session, automation, trigger="test")


async def test_create_run_for_an_empty_document_has_no_steps(session, automation_factory) -> None:
    automation = await automation_factory()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    _, steps = await runs_svc.get_run(session, run.id)
    assert steps == []


# --- restart recovery ----------------------------------------------------------------------


async def test_mark_orphaned_runs_failed(session, automation_factory, ai_step) -> None:
    automation = await automation_factory([ai_step("step_aaaaa"), ai_step("step_bbbbb")])
    queued = await runs_svc.create_run(session, automation, trigger="manual")

    # A second automation with a run that got as far as "running".
    other = await automation_factory([ai_step("step_ccccc")])
    running = await runs_svc.create_run(session, other, trigger="manual")
    running.status = "running"
    _, running_steps = await runs_svc.get_run(session, running.id)
    running_steps[0].status = "running"
    await session.flush()

    # ... and one that already finished, which must be left alone.
    done = await automation_factory()
    finished = await runs_svc.create_run(session, done, trigger="manual")
    finished.status = "succeeded"
    await session.flush()

    assert await runs_svc.mark_orphaned_runs_failed(session) == 2

    # The bulk UPDATEs synchronize the session, so the in-memory objects are current.
    for run_id in (queued.id, running.id):
        run, steps = await runs_svc.get_run(session, run_id)
        assert run.status == "failed"
        assert run.error == runs_svc.RESTART_ERROR
        assert run.ended_at is not None
        assert {s.status for s in steps} == {"cancelled"}

    assert (await runs_svc.get_run(session, finished.id))[0].status == "succeeded"
    assert automation.last_run_status == "failed"


async def test_orphan_recovery_records_a_duration_for_a_run_that_had_started(
    session,
    automation_factory,
    ai_step,
) -> None:
    """`duration_ms` is measured the same way `cancel_run` measures it: a run that never
    started has nothing to measure and keeps a NULL duration."""
    automation = await automation_factory([ai_step("step_aaaaa")])
    started = await runs_svc.create_run(session, automation, trigger="manual")
    started.status = "running"
    started.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await session.flush()

    never_started = await automation_factory([ai_step("step_bbbbb")])
    queued = await runs_svc.create_run(session, never_started, trigger="manual")

    await runs_svc.mark_orphaned_runs_failed(session)

    assert (await runs_svc.get_run(session, started.id))[0].duration_ms >= 5000
    assert (await runs_svc.get_run(session, queued.id))[0].duration_ms is None


async def test_cancelling_a_queued_run_ends_open_event_streams(
    session,
    automation_factory,
    ai_step,
) -> None:
    """Nothing will ever publish to this run again, so an open SSE stream must be told."""
    automation = await automation_factory([ai_step("step_aaaaa")])
    run = await runs_svc.create_run(session, automation, trigger="manual")
    queue = run_events.subscribe(run.id)

    assert await runs_svc.cancel_run(session, run.id) == "cancelled"

    assert await queue.get() is run_events.SENTINEL
    assert run_events.subscriber_count(run.id) == 0


async def test_mark_orphaned_runs_failed_is_a_noop_when_nothing_is_active(
    session,
    automation_factory,
) -> None:
    await automation_factory()
    assert await runs_svc.mark_orphaned_runs_failed(session) == 0


# --- pruning -------------------------------------------------------------------------------


async def test_prune_runs_keeps_the_newest(session, automation_factory, ai_step) -> None:
    automation = await automation_factory([ai_step("step_aaaaa")])
    base = datetime.now(timezone.utc)

    created = []
    for i in range(5):
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run.status = "succeeded"
        run.created_at = base + timedelta(seconds=i)
        created.append(run)
    await session.flush()

    assert await runs_svc.prune_runs(session, automation.id, keep=2) == 3

    remaining = (
        (await session.execute(select(Run).where(Run.automation_id == automation.id)))
        .scalars()
        .all()
    )
    assert {r.id for r in remaining} == {created[-1].id, created[-2].id}
    # Steps of the pruned runs went with them (ON DELETE CASCADE).
    surviving_steps = (await session.execute(select(RunStep))).scalars().all()
    assert {s.run_id for s in surviving_steps} == {created[-1].id, created[-2].id}


async def test_prune_runs_leaves_other_automations_alone(
    session,
    automation_factory,
    ai_step,
) -> None:
    a = await automation_factory([ai_step("step_aaaaa")])
    b = await automation_factory([ai_step("step_bbbbb")])
    for automation in (a, b):
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run.status = "succeeded"
    await session.flush()

    assert await runs_svc.prune_runs(session, a.id, keep=0) == 1
    assert (
        len((await session.execute(select(Run).where(Run.automation_id == b.id))).scalars().all())
        == 1
    )


async def test_prune_runs_below_the_threshold_deletes_nothing(session, automation_factory) -> None:
    automation = await automation_factory()
    await runs_svc.create_run(session, automation, trigger="manual")
    assert await runs_svc.prune_runs(session, automation.id, keep=200) == 0


# --- listing / cancel ----------------------------------------------------------------------


async def test_list_runs_is_newest_first_and_honours_the_cursor(
    session,
    automation_factory,
) -> None:
    automation = await automation_factory()
    base = datetime.now(timezone.utc)
    runs = []
    for i in range(3):
        run = await runs_svc.create_run(session, automation, trigger="manual")
        run.status = "succeeded"
        run.created_at = base + timedelta(seconds=i)
        runs.append(run)
    await session.flush()

    listed = await runs_svc.list_runs(session, automation.id)
    assert [r.id for r in listed] == [runs[2].id, runs[1].id, runs[0].id]

    cursor = int(runs[1].created_at.timestamp() * 1000)
    older = await runs_svc.list_runs(session, automation.id, before=cursor)
    assert [r.id for r in older] == [runs[0].id]

    assert len(await runs_svc.list_runs(session, automation.id, limit=1)) == 1


async def test_cancelling_a_running_run_only_signals_the_task_that_owns_it(
    session,
    automation_factory,
    ai_step,
    monkeypatch,
) -> None:
    """The executor has to unwind the step it is inside, so the run stays `running`."""
    automation = await automation_factory([ai_step("step_aaaaa")])
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run.status = "running"
    await session.flush()

    signalled: list[str] = []
    monkeypatch.setattr(
        runs_svc.executor, "request_cancel", lambda run_id: bool(signalled.append(run_id)) or True
    )

    assert await runs_svc.cancel_run(session, run.id) == "running"
    assert signalled == [run.id]
    assert run.status == "running"


async def test_cancelling_a_running_run_nothing_owns_cancels_it_outright(
    session,
    automation_factory,
    ai_step,
) -> None:
    """A `running` run with no task behind it is a leftover: nothing will ever finish it.

    Leaving it `running` would both lie to the client and block every future run of the
    automation, so `cancel_run` finishes it itself. With no executor task registered,
    `request_cancel` returns False, which is the signal that this is that case.
    """
    automation = await automation_factory([ai_step("step_aaaaa")])
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run.status = "running"
    await session.flush()

    assert await runs_svc.cancel_run(session, run.id) == "cancelled"

    steps = (
        (await session.execute(select(RunStep).where(RunStep.run_id == run.id)))
        .scalars()
        .all()
    )
    assert {s.status for s in steps} == {"cancelled"}
    assert automation.last_run_status == "cancelled"
