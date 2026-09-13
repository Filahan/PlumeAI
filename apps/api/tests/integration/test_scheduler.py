"""`app.services.scheduler` — the projection of the automations table onto APScheduler.

The scheduler under test is a real `AsyncIOScheduler` with a `MemoryJobStore`, installed
through `configure_scheduler` so nothing touches the Postgres jobstore (and nothing leaks
between tests). It is started **paused**, which is what production looks like by the time
any request calls `sync_job`: a stopped scheduler only queues `add_job` calls into a
pending list where `replace_existing` and `get_job` don't apply yet, while a paused one has
a live jobstore and computes fire times but never actually runs a job.
"""

from __future__ import annotations

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
    """Record the run ids `run_scheduled` hands to the executor instead of running them."""
    seen: list[str] = []

    async def fake_execute_run(run_id: str) -> None:
        seen.append(run_id)

    monkeypatch.setattr(sched, "execute_run", fake_execute_run)
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


def test_job_defaults_prevent_overlap_and_catch_up_once() -> None:
    assert sched.JOB_DEFAULTS["max_instances"] == 1
    assert sched.JOB_DEFAULTS["coalesce"] is True
    assert sched.JOB_DEFAULTS["misfire_grace_time"] == 60


async def test_start_survives_a_jobstore_that_cannot_start(monkeypatch) -> None:
    """A broken jobstore must cost us persistence, not the whole scheduler."""
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
