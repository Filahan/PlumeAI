"""The Activity API — `/runs` and `/schedules` read across every automation.

Everything here runs against a real database and a real (paused, memory-backed)
APScheduler, because the three things most likely to break are exactly the three a fake
would get wrong: the join that keeps the run list from going N+1, the millisecond cursor
that has to page without gaps or repeats, and the fact that *pausing a schedule is not an
edit of the document* — it drops the scheduler job and nothing else.

The scheduler is started paused, as `test_scheduler.py` does: a stopped scheduler only
queues `add_job` calls into a pending list (where `get_job` sees nothing), while a paused
one keeps a live jobstore and computes fire times without ever firing.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from apscheduler.jobstores.memory import MemoryJobStore
from sqlalchemy import event, select

from app.db.models import Automation, Run, RunStep
from app.services import automations as svc
from app.services import scheduler as sched

# A fixed, whole-second base time. Whole seconds matter: the `before` cursor is epoch
# *milliseconds* while `created_at` is microsecond-precision, so seeding rows on exact
# millisecond boundaries is what makes "page 2 starts exactly where page 1 stopped" an
# assertion about the endpoint rather than about rounding.
BASE = datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc)


def _document(name: str, trigger: dict) -> dict:
    return {
        "name": name,
        "description": "",
        "model": {"provider": "openai", "model": "gpt-4o-mini"},
        "trigger": trigger,
        "steps": [
            {
                "id": "step_aaaaa",
                "name": "Think",
                "type": "ai",
                "settings": {"instructions": "hi", "tools": [], "output": {"mode": "text"}},
            },
            {
                "id": "step_bbbbb",
                "name": "Think harder",
                "type": "ai",
                "settings": {"instructions": "hi", "tools": [], "output": {"mode": "text"}},
            },
        ],
    }


def cron_document(name: str, cron: str = "0 8 * * 1-5", tz: str | None = "Europe/Paris") -> dict:
    settings: dict = {"mode": "cron", "cron": cron}
    if tz is not None:
        settings["timezone"] = tz
    return _document(name, {"type": "schedule", "settings": settings})


def interval_document(name: str, minutes: int, tz: str | None = None) -> dict:
    settings: dict = {"mode": "interval", "every_minutes": minutes}
    if tz is not None:
        settings["timezone"] = tz
    return _document(name, {"type": "schedule", "settings": settings})


def manual_document(name: str) -> dict:
    return _document(name, {"type": "manual"})


@contextmanager
def count_statements(engine):
    """Count the SQL statements a block of work actually sends to Postgres.

    A cursor-level listener rather than `echo`: it sees every statement SQLAlchemy
    executes (including ones a lazy load would sneak in) and nothing else — no BEGIN, no
    COMMIT, no log parsing.
    """
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


@pytest_asyncio.fixture
async def scheduler():
    """A paused, memory-backed scheduler installed as the process one."""
    instance = sched.build_scheduler(MemoryJobStore())
    instance.start(paused=True)
    sched.configure_scheduler(instance)
    yield instance
    if instance.running:
        instance.shutdown(wait=False)
    sched.configure_scheduler(None)


@pytest_asyncio.fixture
async def seed(session, scheduler):
    """Three scheduled automations, one manual one, and six runs spread across two of them.

    Shaped so every ordering rule the endpoints promise is actually exercised:

    - `gamma` fires every 5 minutes, so it is always due before `alpha`'s weekday 08:00
      cron — the schedule list must put it first whatever day the suite runs on.
    - `beta` is disabled, so it has no scheduler job and no next fire time: it is the row
      that proves nulls sort last rather than first.
    - `delta` is a manual automation, and must not appear in the schedule list at all.
    """
    alpha = await svc.create_automation(session, document=cron_document("Alpha digest"))
    beta = await svc.create_automation(
        session, document=interval_document("Beta sync", 15)
    )
    gamma = await svc.create_automation(
        session, document=interval_document("Gamma poll", 5)
    )
    delta = await svc.create_automation(session, document=manual_document("Delta manual"))
    await svc.set_enabled(session, beta, False)

    # Interleaved across the two automations so "newest first" is a real ordering rather
    # than one automation's history followed by the other's.
    plan = [
        (alpha, "succeeded", 50),
        (beta, "cancelled", 40),
        (alpha, "failed", 30),
        (beta, "succeeded", 20),
        (alpha, "succeeded", 10),
        (beta, "queued", 5),
    ]
    runs: dict[str, Run] = {}
    for index, (automation, status, minutes_ago) in enumerate(plan):
        created = BASE - timedelta(minutes=minutes_ago)
        terminal = status in {"succeeded", "failed", "cancelled"}
        run = Run(
            id=f"run_{index}",
            automation_id=automation.id,
            version_id=automation.current_version_id,
            trigger="schedule",
            status=status,
            input_tokens=0,
            output_tokens=0,
            started_at=created if terminal else None,
            ended_at=created + timedelta(seconds=12) if terminal else None,
            duration_ms=12_000 if terminal else None,
            created_at=created,
        )
        session.add(run)
        runs[run.id] = run

    # Only the oldest run gets steps — the standalone detail endpoint has to return them
    # for a run reached by id alone, with no automation in the URL to scope it.
    for index, step_id in enumerate(("step_aaaaa", "step_bbbbb")):
        session.add(
            RunStep(
                id=f"step_row_{index}",
                run_id="run_0",
                step_id=step_id,
                index=index,
                name=f"Step {index}",
                type="ai",
                status="succeeded",
                attempt=1,
                trace=[],
            )
        )

    alpha.last_run_id, alpha.last_run_status = "run_4", "succeeded"
    beta.last_run_id, beta.last_run_status = "run_5", "queued"
    await session.commit()

    return {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "delta": delta,
        # Newest first — the exact order `GET /runs` has to return.
        "newest_first": ["run_5", "run_4", "run_3", "run_2", "run_1", "run_0"],
    }


# --- GET /runs ---------------------------------------------------------------------------


async def test_the_run_list_is_newest_first_and_names_each_automation(client, seed) -> None:
    body = (await client.get("/runs")).json()

    assert [r["id"] for r in body["runs"]] == seed["newest_first"]
    assert body["nextCursor"] is None  # a short page means there is nothing older

    names = {r["id"]: r["automationName"] for r in body["runs"]}
    assert names["run_4"] == "Alpha digest"
    assert names["run_5"] == "Beta sync"

    newest = body["runs"][0]
    assert newest["automationId"] == seed["beta"].id
    assert newest["status"] == "queued"
    assert newest["versionNumber"] == 1
    assert isinstance(newest["createdAt"], int)


async def test_limit_and_before_page_without_gaps_or_repeats(client, seed) -> None:
    seen: list[str] = []
    cursor = None
    for _ in range(4):  # one more request than it takes, to prove it terminates
        query = "/runs?limit=2" + (f"&before={cursor}" if cursor is not None else "")
        body = (await client.get(query)).json()
        seen.extend(r["id"] for r in body["runs"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert seen == seed["newest_first"]
    assert len(set(seen)) == len(seen)
    assert cursor is None


async def test_the_cursor_of_a_full_last_page_yields_an_empty_one(client, seed) -> None:
    """Six runs at `limit=3` means the second page is full too — the endpoint cannot know
    it was the last one, so it hands back a cursor that simply returns nothing."""
    first = (await client.get("/runs?limit=3")).json()
    second = (await client.get(f"/runs?limit=3&before={first['nextCursor']}")).json()
    assert [r["id"] for r in second["runs"]] == ["run_2", "run_1", "run_0"]

    third = (await client.get(f"/runs?limit=3&before={second['nextCursor']}")).json()
    assert third["runs"] == []
    assert third["nextCursor"] is None


async def test_automation_id_filters_the_list(client, seed) -> None:
    body = (await client.get(f"/runs?automationId={seed['alpha'].id}")).json()

    assert [r["id"] for r in body["runs"]] == ["run_4", "run_2", "run_0"]
    assert {r["automationName"] for r in body["runs"]} == {"Alpha digest"}


async def test_status_is_repeatable_and_filters_the_list(client, seed) -> None:
    one = (await client.get("/runs?status=failed")).json()
    assert [r["id"] for r in one["runs"]] == ["run_2"]

    many = (await client.get("/runs?status=failed&status=cancelled&status=queued")).json()
    assert [r["id"] for r in many["runs"]] == ["run_5", "run_2", "run_1"]


async def test_an_unknown_status_is_rejected(client, seed) -> None:
    assert (await client.get("/runs?status=exploded")).status_code == 422


async def test_filters_and_the_cursor_combine(client, seed) -> None:
    body = (
        await client.get(f"/runs?automationId={seed['alpha'].id}&status=succeeded&limit=1")
    ).json()
    assert [r["id"] for r in body["runs"]] == ["run_4"]

    older = (
        await client.get(
            f"/runs?automationId={seed['alpha'].id}&status=succeeded"
            f"&before={body['nextCursor']}"
        )
    ).json()
    assert [r["id"] for r in older["runs"]] == ["run_0"]


# --- GET /runs/{run_id} ------------------------------------------------------------------


async def test_a_run_can_be_fetched_by_id_alone(client, seed) -> None:
    body = (await client.get("/runs/run_0")).json()

    assert body["id"] == "run_0"
    assert body["automationId"] == seed["alpha"].id
    assert body["automationName"] == "Alpha digest"
    assert body["versionNumber"] == 1
    assert [s["stepId"] for s in body["steps"]] == ["step_aaaaa", "step_bbbbb"]
    assert [s["status"] for s in body["steps"]] == ["succeeded", "succeeded"]


async def test_an_unknown_run_is_404(client, seed) -> None:
    assert (await client.get("/runs/nope")).status_code == 404


# --- GET /schedules ----------------------------------------------------------------------


async def test_schedules_lists_only_scheduled_automations(client, seed) -> None:
    body = (await client.get("/schedules")).json()

    assert body["timezone"] == "UTC"  # the workspace default
    ids = [s["automationId"] for s in body["schedules"]]
    assert seed["delta"].id not in ids  # the manual automation is not a schedule
    assert set(ids) == {seed["alpha"].id, seed["beta"].id, seed["gamma"].id}


async def test_schedules_report_the_trigger_verbatim_and_its_own_timezone(
    client, seed
) -> None:
    by_id = {s["automationId"]: s for s in (await client.get("/schedules")).json()["schedules"]}

    alpha = by_id[seed["alpha"].id]
    assert alpha["triggerSummary"] == "weekdays at 08:00"  # describe_trigger's wording
    assert alpha["mode"] == "cron"
    assert alpha["cron"] == "0 8 * * 1-5"
    assert alpha["everyMinutes"] is None
    assert alpha["timezone"] == "Europe/Paris"

    beta = by_id[seed["beta"].id]
    assert beta["triggerSummary"] == "every 15 minutes"
    assert beta["mode"] == "interval"
    assert beta["cron"] is None
    assert beta["everyMinutes"] == 15
    # No zone of its own: it inherits the workspace one reported at the top level.
    assert beta["timezone"] is None


async def test_schedules_are_ordered_by_next_run_at_with_nulls_last(client, seed) -> None:
    body = (await client.get("/schedules")).json()
    ids = [s["automationId"] for s in body["schedules"]]

    # gamma (every 5 minutes) is always due before alpha (weekdays at 08:00); beta is
    # disabled, so it holds no job and sorts last.
    assert ids == [seed["gamma"].id, seed["alpha"].id, seed["beta"].id]

    fire_times = [s["nextRunAt"] for s in body["schedules"]]
    assert fire_times[0] is not None and fire_times[1] is not None
    assert fire_times[0] < fire_times[1]
    assert fire_times[2] is None
    assert [s["enabled"] for s in body["schedules"]] == [True, True, False]


async def test_schedules_report_the_last_run(client, seed) -> None:
    by_id = {s["automationId"]: s for s in (await client.get("/schedules")).json()["schedules"]}

    alpha = by_id[seed["alpha"].id]["lastRun"]
    assert alpha["id"] == "run_4"
    assert alpha["status"] == "succeeded"
    assert alpha["durationMs"] == 12_000
    assert isinstance(alpha["endedAt"], int)

    # Still queued, so it has neither an end nor a duration yet.
    beta = by_id[seed["beta"].id]["lastRun"]
    assert beta == {"id": "run_5", "status": "queued", "endedAt": None, "durationMs": None}

    # Never ran at all.
    assert by_id[seed["gamma"].id]["lastRun"] is None


# --- pause / resume ----------------------------------------------------------------------


async def _enabled(session, automation_id: str) -> bool:
    """Read `enabled` straight out of the table.

    A column select rather than a re-`get` of the ORM object: the API wrote through its
    *own* session, so anything still sitting in this test session's identity map is stale
    by definition — and expiring it would make the next attribute access try to refresh
    itself outside the async greenlet.
    """
    return (
        await session.execute(
            select(Automation.enabled).where(Automation.id == automation_id)
        )
    ).scalar_one()


async def _document_of(session, automation_id: str) -> dict:
    """The stored document as it is on disk right now — see `_enabled`."""
    return (
        await session.execute(
            select(Automation.document).where(Automation.id == automation_id)
        )
    ).scalar_one()


async def test_pause_with_explicit_ids_changes_exactly_those(client, seed, session) -> None:
    body = (
        await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})
    ).json()

    assert body == {"changed": 1, "automationIds": [seed["alpha"].id]}
    assert await _enabled(session, seed["alpha"].id) is False
    assert await _enabled(session, seed["gamma"].id) is True
    assert sched.next_run_at(seed["alpha"].id) is None
    assert sched.next_run_at(seed["gamma"].id) is not None


async def test_pausing_leaves_the_schedule_trigger_in_the_document(
    client, seed, session
) -> None:
    await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})

    document = await _document_of(session, seed["alpha"].id)
    assert document["trigger"] == {
        "type": "schedule",
        "settings": {"mode": "cron", "cron": "0 8 * * 1-5", "timezone": "Europe/Paris"},
    }
    # And the list still shows it, paused, with the same summary and no fire time.
    row = next(
        s
        for s in (await client.get("/schedules")).json()["schedules"]
        if s["automationId"] == seed["alpha"].id
    )
    assert row["enabled"] is False
    assert row["triggerSummary"] == "weekdays at 08:00"
    assert row["nextRunAt"] is None


async def test_pausing_twice_changes_nothing_the_second_time(client, seed) -> None:
    first = (
        await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})
    ).json()
    second = (
        await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})
    ).json()

    assert first["changed"] == 1
    assert second == {"changed": 0, "automationIds": []}


async def test_pause_with_null_pauses_every_scheduled_automation(
    client, seed, session
) -> None:
    body = (await client.post("/schedules/pause", json={"automationIds": None})).json()

    # beta was already disabled, so only the two enabled schedules flipped.
    assert set(body["automationIds"]) == {seed["alpha"].id, seed["gamma"].id}
    assert body["changed"] == 2
    assert all(s["nextRunAt"] is None for s in (await client.get("/schedules")).json()["schedules"])
    # The manual automation is not a schedule and must not have been touched.
    assert await _enabled(session, seed["delta"].id) is True


async def test_resume_restores_paused_schedules(client, seed, session) -> None:
    await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})
    body = (
        await client.post("/schedules/resume", json={"automationIds": [seed["alpha"].id]})
    ).json()

    assert body == {"changed": 1, "automationIds": [seed["alpha"].id]}
    assert await _enabled(session, seed["alpha"].id) is True
    assert sched.next_run_at(seed["alpha"].id) is not None


async def test_an_omitted_body_field_means_every_schedule(client, seed) -> None:
    body = (await client.post("/schedules/resume", json={})).json()
    assert set(body["automationIds"]) == {seed["beta"].id}  # the only disabled one


async def test_unknown_and_unscheduled_ids_are_ignored(client, seed) -> None:
    body = (
        await client.post(
            "/schedules/pause",
            json={"automationIds": ["nope", seed["delta"].id, seed["gamma"].id]},
        )
    ).json()
    assert body == {"changed": 1, "automationIds": [seed["gamma"].id]}


async def test_a_paused_automation_can_still_be_run_by_hand(client, seed) -> None:
    """Pausing stops the *scheduler*, not the automation: the run button still works."""
    await client.post("/schedules/pause", json={"automationIds": [seed["alpha"].id]})

    resp = await client.post(f"/automations/{seed['alpha'].id}/runs", json={})
    assert resp.status_code == 202, resp.text
    assert resp.json()["runId"]


# --- query budget ------------------------------------------------------------------------


@pytest.mark.parametrize("run_count", [2, 20])
async def test_the_run_list_does_not_go_n_plus_one(
    client, session, engine, scheduler, run_count
) -> None:
    """The number of statements must not grow with the number of rows returned.

    The automation name and version number of every run come out of one joined query; a
    regression that resolved either per row would turn this into `run_count + 1`.
    """
    automation = await svc.create_automation(session, document=manual_document("Busy"))
    for index in range(run_count):
        session.add(
            Run(
                id=f"bulk_{index}",
                automation_id=automation.id,
                version_id=automation.current_version_id,
                trigger="manual",
                status="succeeded",
                input_tokens=0,
                output_tokens=0,
                started_at=BASE - timedelta(minutes=index),
                ended_at=BASE - timedelta(minutes=index) + timedelta(seconds=1),
                duration_ms=1_000,
                created_at=BASE - timedelta(minutes=index),
            )
        )
    await session.commit()

    with count_statements(engine) as statements:
        body = (await client.get("/runs")).json()

    assert len(body["runs"]) == run_count
    assert len(statements) <= 2, statements
