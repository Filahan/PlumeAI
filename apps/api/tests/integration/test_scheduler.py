"""`app.services.scheduler` — the projection of the automations table onto APScheduler.

The scheduler under test is a real `AsyncIOScheduler` with a `MemoryJobStore`, installed
through `configure_scheduler` so nothing touches the Postgres jobstore (and nothing leaks
between tests). It is started **paused**, which is what production looks like by the time
any request calls `sync_job`: a stopped scheduler only queues `add_job` calls into a
pending list where `replace_existing` and `get_job` don't apply yet, while a paused one has
a live jobstore and computes fire times but never actually runs a job.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from apscheduler.jobstores.memory import MemoryJobStore

from app.errors import Conflict
from app.services import automations as svc
from app.services import runs as runs_svc
from app.services import scheduler as sched


@pytest_asyncio.fixture
async def scheduler():
    """A paused, memory-backed scheduler installed as the process one.

    Async so that it is torn down while this test's event loop is still open — an
    `AsyncIOScheduler` needs the loop to shut down.
    """
    instance = sched.build_scheduler(MemoryJobStore())
    instance.start(paused=True)
    sched.configure_scheduler(instance)
    yield instance
    if instance.running:
        instance.shutdown(wait=False)
    sched.configure_scheduler(None)


def cron_document(cron: str = "0 8 * * 1-5", tz: str | None = "Europe/Paris") -> dict:
    settings: dict = {"mode": "cron", "cron": cron}
    if tz is not None:
        settings["timezone"] = tz
    return _document({"type": "schedule", "settings": settings})


def interval_document(minutes: int = 15, tz: str | None = "UTC") -> dict:
    settings: dict = {"mode": "interval", "every_minutes": minutes}
    if tz is not None:
        settings["timezone"] = tz
    return _document({"type": "schedule", "settings": settings})


def manual_document() -> dict:
    return _document({"type": "manual"})


def _document(trigger: dict) -> dict:
    return {
        "name": "Scheduled demo",
        "description": "",
        "model": {"provider": "openai", "model": "gpt-4o-mini"},
        "trigger": trigger,
        "steps": [
            {
                "id": "step_aaaaa",
                "name": "Think",
                "type": "ai",
                "settings": {"instructions": "hi", "tools": [], "output": {"mode": "text"}},
            }
        ],
    }


@pytest.fixture
def automation_factory(session):
    async def build(document: dict, *, enabled: bool = True):
        automation = await svc.create_automation(session, document=document)
        automation.enabled = enabled
        await session.commit()
        return automation

    return build


# --- sync_job ----------------------------------------------------------------------------


async def test_a_cron_trigger_becomes_a_cron_job_in_its_own_timezone(
    scheduler, automation_factory
) -> None:
    automation = await automation_factory(cron_document("0 8 * * 1-5", "Europe/Paris"))

    sched.sync_job(automation)

    job = scheduler.get_job(automation.id)
    assert job is not None
    assert list(job.args) == [automation.id]
    assert job.name == automation.name
    assert str(job.trigger.timezone) == "Europe/Paris"
    # The crontab fields survived the translation.
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "8"
    assert fields["minute"] == "0"
    assert fields["day_of_week"] == "1-5"


async def test_an_interval_trigger_becomes_an_interval_job(
    scheduler, automation_factory
) -> None:
    automation = await automation_factory(interval_document(15, "UTC"))

    sched.sync_job(automation)

    job = scheduler.get_job(automation.id)
    assert job.trigger.interval == timedelta(minutes=15)


async def test_a_schedule_without_a_timezone_falls_back_to_the_workspace_one(
    scheduler, automation_factory
) -> None:
    automation = await automation_factory(cron_document("*/5 * * * *", tz=None))

    sched.sync_job(automation, timezone="Asia/Tokyo")

    assert str(scheduler.get_job(automation.id).trigger.timezone) == "Asia/Tokyo"


async def test_the_schedules_own_timezone_wins_over_the_workspace_one(
    scheduler, automation_factory
) -> None:
    automation = await automation_factory(cron_document("*/5 * * * *", "Europe/Paris"))

    sched.sync_job(automation, timezone="Asia/Tokyo")

    assert str(scheduler.get_job(automation.id).trigger.timezone) == "Europe/Paris"


async def test_a_manual_trigger_gets_no_job(scheduler, automation_factory) -> None:
    automation = await automation_factory(manual_document())

    sched.sync_job(automation)

    assert scheduler.get_job(automation.id) is None


async def test_a_disabled_automation_gets_no_job(scheduler, automation_factory) -> None:
    automation = await automation_factory(cron_document(), enabled=False)

    sched.sync_job(automation)

    assert scheduler.get_job(automation.id) is None


async def test_syncing_replaces_the_existing_job_rather_than_adding_a_second(
    scheduler, automation_factory, session
) -> None:
    automation = await automation_factory(cron_document("0 8 * * *"))
    sched.sync_job(automation)

    await svc.save_document(
        session, automation, interval_document(30, "UTC"), created_by="user"
    )
    await session.commit()
    sched.sync_job(automation)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].trigger.interval == timedelta(minutes=30)


async def test_disabling_an_automation_drops_its_job(
    scheduler, automation_factory, session
) -> None:
    automation = await automation_factory(cron_document())
    sched.sync_job(automation)
    assert scheduler.get_job(automation.id) is not None

    await svc.set_enabled(session, automation, False)
    await session.commit()
    sched.sync_job(automation)

    assert scheduler.get_jobs() == []


async def test_switching_to_a_manual_trigger_drops_the_job(
    scheduler, automation_factory, session
) -> None:
    automation = await automation_factory(cron_document())
    sched.sync_job(automation)

    await svc.save_document(session, automation, manual_document(), created_by="user")
    await session.commit()
    sched.sync_job(automation)

    assert scheduler.get_jobs() == []


async def test_jobs_reference_their_function_by_name_so_they_survive_a_restart(
    scheduler, automation_factory
) -> None:
    """A pickled job that stored a function *object* breaks when the code moves."""
    automation = await automation_factory(cron_document())

    sched.sync_job(automation)

    assert scheduler.get_job(automation.id).func_ref == "app.services.scheduler:run_scheduled"


async def test_an_unschedulable_trigger_is_logged_and_skipped_not_raised(scheduler) -> None:
    """A draft can hold a trigger the scheduler cannot build; saving it must still work."""

    class Draft:
        id = "a1"
        name = "Broken"
        enabled = True
        document = {"trigger": {"type": "schedule", "settings": {"mode": "cron"}}}

    sched.sync_job(Draft())

    assert scheduler.get_jobs() == []


async def test_sync_job_is_inert_when_no_scheduler_is_running(automation_factory) -> None:
    """Request handlers call `sync_job` in processes with no scheduler (tests, workers)."""
    automation = await automation_factory(cron_document())

    sched.configure_scheduler(None)
    sched.sync_job(automation)  # must not raise, must not build a scheduler
    sched.remove_job(automation.id)

    assert sched.next_run_at(automation.id) is None


# --- remove_job / next_run_at ------------------------------------------------------------


async def test_remove_job_drops_it(scheduler, automation_factory) -> None:
    automation = await automation_factory(cron_document())
    sched.sync_job(automation)

    sched.remove_job(automation.id)

    assert scheduler.get_job(automation.id) is None


async def test_removing_a_job_that_is_not_there_is_fine(scheduler) -> None:
    sched.remove_job("never-existed")


async def test_next_run_at_is_epoch_milliseconds(scheduler, automation_factory) -> None:
    automation = await automation_factory(interval_document(60, "UTC"))
    sched.sync_job(automation)

    when = sched.next_run_at(automation.id)

    assert isinstance(when, int)
    expected = datetime.now(timezone.utc) + timedelta(minutes=60)
    assert abs(when - int(expected.timestamp() * 1000)) < 60_000


async def test_next_run_at_is_none_for_an_automation_with_no_job(
    scheduler, automation_factory
) -> None:
    automation = await automation_factory(manual_document())
    sched.sync_job(automation)

    assert sched.next_run_at(automation.id) is None


# --- reload_all --------------------------------------------------------------------------


async def test_reload_all_rebuilds_the_job_set_from_the_table(
    scheduler, automation_factory
) -> None:
    scheduled = await automation_factory(cron_document())
    interval = await automation_factory(interval_document(5, "UTC"))
    manual = await automation_factory(manual_document())
    disabled = await automation_factory(cron_document(), enabled=False)

    await sched.reload_all()

    assert {j.id for j in scheduler.get_jobs()} == {scheduled.id, interval.id}
    assert sched.next_run_at(manual.id) is None
    assert scheduler.get_job(disabled.id) is None


async def test_reload_all_drops_jobs_whose_automation_is_gone(
    scheduler, automation_factory, session
) -> None:
    """A jobstore that outlived its automations must not keep firing them."""
    automation = await automation_factory(cron_document())
    sched.sync_job(automation)
    scheduler.add_job(
        sched.JOB_FUNC,
        trigger="interval",
        minutes=1,
        id="ghost",
        args=["ghost"],
    )

    await sched.reload_all()

    assert {j.id for j in scheduler.get_jobs()} == {automation.id}


async def test_reload_all_uses_the_workspace_timezone(
    scheduler, automation_factory, session
) -> None:
    from app.db.models import Settings as SettingsRow

    session.add(
        SettingsRow(
            id=1,
            providers=[],
            default_model={"provider": "openai", "model": "gpt-4o-mini"},
            tools={},
            tool_credentials={},
            timezone="Asia/Tokyo",
        )
    )
    await session.commit()
    automation = await automation_factory(cron_document("0 9 * * *", tz=None))

    await sched.reload_all()

    assert str(scheduler.get_job(automation.id).trigger.timezone) == "Asia/Tokyo"


# --- run_scheduled -----------------------------------------------------------------------


@pytest.fixture
def executed(monkeypatch) -> list[str]:
    """Record the run ids `run_scheduled` hands to the executor instead of running them.

    Patched at `start_run_in_background`, which is how `run_scheduled` starts a run — going
    through the executor's task registry is what makes a scheduled run cancellable, so the
    fake still has to hand back a real awaitable task.
    """
    seen: list[str] = []

    def fake_start(run_id: str) -> asyncio.Task[None]:
        seen.append(run_id)
        return asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(sched, "start_run_in_background", fake_start)
    return seen


async def test_run_scheduled_creates_a_run_and_executes_it(
    scheduler, automation_factory, executed, session
) -> None:
    automation = await automation_factory(cron_document())
    automation_id = automation.id

    await sched.run_scheduled(automation_id)

    runs = await runs_svc.list_runs(session, automation_id)
    assert [r.trigger for r in runs] == ["schedule"]
    assert executed == [runs[0].id]
    # The run was committed before the executor was handed its id — it opens its own session.
    assert runs[0].status == "queued"


async def test_run_scheduled_skips_when_a_run_is_already_in_flight(
    scheduler, automation_factory, executed, session
) -> None:
    """`max_instances=1` covers overlapping *fires*; this covers a manual run in flight."""
    automation = await automation_factory(cron_document())
    automation_id = automation.id
    existing = await runs_svc.create_run(session, automation, trigger="manual")
    existing_id = existing.id
    await session.commit()

    await sched.run_scheduled(automation_id)

    assert executed == []
    runs = await runs_svc.list_runs(session, automation_id)
    assert [r.id for r in runs] == [existing_id]


async def test_create_run_really_does_conflict(automation_factory, session) -> None:
    """The 409 `run_scheduled` relies on, asserted directly."""
    automation = await automation_factory(cron_document())
    await runs_svc.create_run(session, automation, trigger="manual")
    await session.commit()

    with pytest.raises(Conflict):
        await runs_svc.create_run(session, automation, trigger="schedule")


async def test_run_scheduled_skips_a_disabled_automation(
    scheduler, automation_factory, executed, session
) -> None:
    automation = await automation_factory(cron_document(), enabled=False)
    automation_id = automation.id

    await sched.run_scheduled(automation_id)

    assert executed == []
    assert await runs_svc.list_runs(session, automation_id) == []


async def test_run_scheduled_for_a_deleted_automation_drops_its_job(
    scheduler, automation_factory, executed
) -> None:
    automation = await automation_factory(cron_document())
    automation_id = automation.id
    sched.sync_job(automation)

    await sched.run_scheduled("gone-for-good")
    assert executed == []

    # And a job for an id that no longer resolves cleans itself up.
    scheduler.add_job(
        sched.JOB_FUNC, trigger="interval", minutes=1, id="gone", args=["gone"]
    )
    await sched.run_scheduled("gone")
    assert {j.id for j in scheduler.get_jobs()} == {automation_id}


# --- plumbing ----------------------------------------------------------------------------


def test_the_jobstore_url_uses_a_sync_driver() -> None:
    """APScheduler 3's SQLAlchemy jobstore is synchronous — asyncpg would not work."""
    url = sched.sync_database_url()

    assert url.startswith("postgresql+psycopg://")
    assert "asyncpg" not in url


async def test_a_real_job_cannot_overlap_itself_and_catches_up_once(
    scheduler, automation_factory
) -> None:
    """Asserted on the job APScheduler actually built, not on the defaults dict."""
    automation = await automation_factory(interval_document(1, "UTC"))

    sched.sync_job(automation)

    job = scheduler.get_job(automation.id)
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 60


async def test_an_unreachable_jobstore_falls_back_to_memory(monkeypatch) -> None:
    """Losing persistence is survivable; losing schedules is not."""

    def _explode(**_kwargs):
        raise RuntimeError("driver missing")

    monkeypatch.setattr(
        "apscheduler.jobstores.sqlalchemy.SQLAlchemyJobStore", _explode, raising=True
    )

    built = sched.build_scheduler()
    try:
        assert isinstance(built._jobstores["default"], MemoryJobStore)
    finally:
        if built.running:
            built.shutdown(wait=False)


async def test_start_survives_a_jobstore_that_cannot_start(engine, monkeypatch) -> None:
    """A broken jobstore must cost us persistence, not the whole scheduler.

    Takes `engine` because `start()` ends in `reload_all()`, which opens a session — without
    it the reload would read the *development* database instead of the throwaway one.
    """
    broken = sched.build_scheduler(MemoryJobStore())

    def _explode(*_a, **_k):
        raise RuntimeError("no jobs table")

    monkeypatch.setattr(broken, "start", _explode)
    sched.configure_scheduler(broken)
    try:
        await sched.start()
        running = sched.get_scheduler()
        assert running is not broken
        assert running.running
        running.shutdown(wait=False)
    finally:
        sched.configure_scheduler(None)


async def test_shutdown_is_a_no_op_when_nothing_is_running() -> None:
    sched.configure_scheduler(None)
    await sched.shutdown()


# --- the scheduled path, end to end -----------------------------------------------------


async def test_a_firing_job_runs_the_automation_all_the_way_to_a_terminal_row(
    scheduler, session, monkeypatch
) -> None:
    """The whole scheduled path with nothing faked but the outside world.

    A real job on the real scheduler, fired the way APScheduler fires it, through
    `run_scheduled` → `create_run` → the real executor → a terminal `runs` row. Only the
    tool registry is stubbed, so the automation "does" something without leaving the box.
    """
    from app.agent import runner as agent_runner
    from app.services import executor, step_runner
    from app.tools.base import ToolResult

    calls: list[dict] = []

    async def fake_execute_tool(name: str, raw_args: str, _session) -> ToolResult:
        calls.append({"tool": name, "args": json.loads(raw_args)})
        return ToolResult(ok=True, content="{}", data={"fetched": True})

    monkeypatch.setattr(step_runner, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(agent_runner, "execute_tool", fake_execute_tool)

    document = _document({"type": "schedule", "settings": {"mode": "interval", "every_minutes": 1}})
    document["steps"] = [
        {
            "id": "step_fetch0",
            "name": "Fetch",
            "type": "action",
            "settings": {
                "integration": "builtin",
                "action": "http",
                "input": {"url": {"kind": "literal", "value": "https://example.com"}},
            },
        }
    ]
    automation = await svc.create_automation(session, document=document)
    automation_id = automation.id
    await session.commit()

    sched.sync_job(automation, timezone="UTC")
    job = scheduler.get_job(automation_id)
    assert job is not None

    # Fire it exactly as the scheduler would: by its stored function reference and args.
    await sched.run_scheduled(*job.args)

    session.expire_all()
    runs = await runs_svc.list_runs(session, automation_id)
    assert len(runs) == 1
    run, steps = await runs_svc.get_run(session, runs[0].id)
    assert run.trigger == "schedule"
    assert run.status == "succeeded"
    assert run.ended_at is not None
    assert [s.status for s in steps] == ["succeeded"]
    assert steps[0].output == {"fetched": True}
    assert calls == [{"tool": "http", "args": {"url": "https://example.com"}}]
    # The run went through the executor's registry, so it was cancellable throughout.
    assert executor.RUNNING_TASKS == {}


async def test_a_scheduled_run_is_registered_so_it_can_be_cancelled(
    scheduler, session, monkeypatch
) -> None:
    """A scheduled run must be reachable by `POST /runs/{id}/cancel` like a manual one."""
    from app.services import executor, step_runner
    from app.tools.base import ToolResult

    entered = asyncio.Event()
    seen: list[dict[str, asyncio.Task]] = []

    async def hanging_tool(name: str, raw_args: str, _session) -> ToolResult:
        entered.set()
        seen.append(dict(executor.RUNNING_TASKS))
        await asyncio.sleep(30)
        return ToolResult(ok=True, content="{}", data={})

    monkeypatch.setattr(step_runner, "execute_tool", hanging_tool)

    document = _document({"type": "schedule", "settings": {"mode": "interval", "every_minutes": 1}})
    document["steps"] = [
        {
            "id": "step_fetch0",
            "name": "Fetch",
            "type": "action",
            "settings": {
                "integration": "builtin",
                "action": "http",
                "input": {"url": {"kind": "literal", "value": "https://example.com"}},
            },
        }
    ]
    automation = await svc.create_automation(session, document=document)
    automation_id = automation.id
    await session.commit()

    job = asyncio.create_task(sched.run_scheduled(automation_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert len(seen[0]) == 1
        run_id = next(iter(seen[0]))
        assert executor.request_cancel(run_id) is True
        await asyncio.wait_for(job, timeout=5)

        session.expire_all()
        run, steps = await runs_svc.get_run(session, run_id)
        assert run.status == "cancelled"
        assert [s.status for s in steps] == ["cancelled"]
    finally:
        job.cancel()
        for task in list(executor.RUNNING_TASKS.values()):
            task.cancel()
        executor.RUNNING_TASKS.clear()
