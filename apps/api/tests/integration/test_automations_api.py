"""End-to-end behavior of the `/automations` API against a real database."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db.models import Automation, Run, RunStep
from tests.integration.conftest import ai_step, document


async def _create(client, **body) -> dict:
    resp = await client.post("/automations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- creation ----------------------------------------------------------------------------


async def test_create_blank_automation_returns_a_usable_draft(client) -> None:
    detail = await _create(client, name="Demo")

    assert detail["name"] == "Demo"
    assert detail["enabled"] is True
    assert detail["versionNumber"] == 1
    assert detail["issues"] == []
    assert detail["nextRunAt"] is None
    assert detail["assistantMessages"] == []
    assert detail["lastRun"] is None
    assert isinstance(detail["createdAt"], int)

    doc = detail["document"]
    assert doc["name"] == "Demo"
    assert doc["trigger"] == {"type": "manual"}
    assert doc["steps"] == []
    # The default model comes from workspace settings, not from the request.
    assert doc["model"]["provider"] in {"openai", "anthropic"}


async def test_create_with_a_document_keeps_it_verbatim(client) -> None:
    detail = await _create(client, document=document("Digest", [ai_step("step_aaaaa")]))

    assert detail["name"] == "Digest"
    assert [s["id"] for s in detail["document"]["steps"]] == ["step_aaaaa"]


async def test_create_with_an_invalid_document_is_422(client) -> None:
    resp = await client.post("/automations", json={"document": {"name": "broken"}})
    assert resp.status_code == 422
    assert resp.json()["extra"]["issues"]


async def test_get_and_list_reflect_the_created_automation(client) -> None:
    created = await _create(client, name="Demo")

    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert detail["id"] == created["id"]

    rows = (await client.get("/automations")).json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["triggerSummary"] == "manual trigger"
    assert rows[0]["valid"] is True
    assert rows[0]["lastRun"] is None


async def test_get_unknown_automation_is_404(client) -> None:
    assert (await client.get("/automations/nope")).status_code == 404


# --- operations --------------------------------------------------------------------------


async def test_operations_add_update_remove_bump_versions_and_summarize(client) -> None:
    created = await _create(client, name="Demo")
    aid = created["id"]

    added = (
        await client.post(
            f"/automations/{aid}/operations",
            json={"operations": [{"op": "add_step", "step": ai_step("step_aaaaa")}]},
        )
    ).json()
    assert [s["id"] for s in added["document"]["steps"]] == ["step_aaaaa"]
    assert added["versionNumber"] == 2
    assert any("Draft a reply" in line for line in added["summary"])

    updated = (
        await client.post(
            f"/automations/{aid}/operations",
            json={
                "operations": [
                    {
                        "op": "update_step",
                        "step_id": "step_aaaaa",
                        "patch": {"name": "Renamed step"},
                    }
                ]
            },
        )
    ).json()
    assert updated["document"]["steps"][0]["name"] == "Renamed step"
    # `patch` merges: the settings the step already had survive the rename.
    assert updated["document"]["steps"][0]["settings"]["instructions"] == "Say hi"
    assert updated["versionNumber"] == 3

    removed = (
        await client.post(
            f"/automations/{aid}/operations",
            json={"operations": [{"op": "remove_step", "step_id": "step_aaaaa"}]},
        )
    ).json()
    assert removed["document"]["steps"] == []
    assert removed["versionNumber"] == 4


async def test_a_no_op_edit_does_not_create_a_version(client) -> None:
    created = await _create(client, name="Demo")
    aid = created["id"]

    first = (
        await client.post(
            f"/automations/{aid}/operations",
            json={"operations": [{"op": "set_meta", "name": "Renamed"}]},
        )
    ).json()
    again = (
        await client.post(
            f"/automations/{aid}/operations",
            json={"operations": [{"op": "set_meta", "name": "Renamed"}]},
        )
    ).json()

    assert again["versionNumber"] == first["versionNumber"]
    assert again["summary"] == []


async def test_operations_on_an_unknown_step_is_400(client) -> None:
    created = await _create(client, name="Demo")
    resp = await client.post(
        f"/automations/{created['id']}/operations",
        json={"operations": [{"op": "remove_step", "step_id": "step_zzzzz"}]},
    )
    assert resp.status_code == 400


async def test_invalid_steps_are_saved_as_a_draft_with_issues(client) -> None:
    """A half-finished automation must still save — the client renders `issues`."""
    created = await _create(client, name="Demo")
    broken = {
        "id": "step_bbbbb",
        "name": "Do the thing",
        "type": "action",
        "settings": {"integration": "gmail", "action": "no_such_action", "input": {}},
    }
    resp = await client.post(
        f"/automations/{created['id']}/operations",
        json={"operations": [{"op": "add_step", "step": broken}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["level"] == "error" for i in body["issues"])
    assert body["document"]["steps"][0]["valid"] is False

    # And the list view reports the automation as invalid, from the stored flags.
    rows = (await client.get("/automations")).json()
    assert rows[0]["valid"] is False


# --- PUT (raw JSON document) --------------------------------------------------------------


async def test_put_an_invalid_document_is_422_with_issues(client) -> None:
    created = await _create(client, name="Demo")
    resp = await client.put(
        f"/automations/{created['id']}",
        json={"document": {"name": "x", "trigger": {"type": "nonsense"}}},
    )
    assert resp.status_code == 422
    issues = resp.json()["extra"]["issues"]
    assert issues and all({"path", "message", "level"} <= set(i) for i in issues)

    # Nothing was written: the draft is still the empty one from creation.
    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert detail["versionNumber"] == 1


async def test_put_a_valid_document_creates_a_new_version(client) -> None:
    created = await _create(client, name="Demo")
    resp = await client.put(
        f"/automations/{created['id']}",
        json={"document": document("Replaced", [ai_step("step_ccccc")])},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["versionNumber"] == 2
    assert body["document"]["name"] == "Replaced"
    assert any("Replaced" in line for line in body["summary"])

    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert detail["name"] == "Replaced"


# --- validate ------------------------------------------------------------------------------


async def test_validate_reports_issues_without_persisting(client) -> None:
    created = await _create(client, name="Demo")
    broken = {
        "id": "step_ddddd",
        "name": "Do the thing",
        "type": "action",
        "settings": {"integration": "gmail", "action": "no_such_action", "input": {}},
    }
    resp = await client.post(
        "/automations/validate", json={"document": document("Scratch", [broken])}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["level"] == "error" for i in body["issues"])
    assert body["document"]["steps"][0]["valid"] is False

    # The stored automation is untouched — validate never writes.
    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert detail["document"]["steps"] == []
    assert detail["versionNumber"] == 1


async def test_validate_route_is_not_shadowed_by_the_id_route(client) -> None:
    """`/automations/validate` must resolve to the validate endpoint, not to an id."""
    resp = await client.post("/automations/validate", json={"document": document()})
    assert resp.status_code == 200


# --- versions ------------------------------------------------------------------------------


async def test_versions_list_fetch_and_restore(client) -> None:
    created = await _create(client, name="Demo")
    aid = created["id"]
    await client.post(
        f"/automations/{aid}/operations",
        json={"operations": [{"op": "add_step", "step": ai_step("step_eeeee")}]},
    )

    versions = (await client.get(f"/automations/{aid}/versions")).json()
    assert [v["number"] for v in versions] == [2, 1]
    assert versions[0]["createdBy"] == "user"

    v1 = (await client.get(f"/automations/{aid}/versions/1")).json()
    assert v1["number"] == 1
    assert v1["document"]["steps"] == []

    restored = (await client.post(f"/automations/{aid}/versions/1/restore")).json()
    assert restored["versionNumber"] == 3
    assert restored["document"]["steps"] == []
    assert any("Removed" in line or "step" in line.lower() for line in restored["summary"])

    versions = (await client.get(f"/automations/{aid}/versions")).json()
    assert versions[0]["createdBy"] == "restore"


async def test_fetching_an_unknown_version_is_404(client) -> None:
    created = await _create(client, name="Demo")
    assert (await client.get(f"/automations/{created['id']}/versions/99")).status_code == 404


# --- patch / delete ------------------------------------------------------------------------


async def test_patch_renames_row_and_document_together(client) -> None:
    created = await _create(client, name="Demo")
    detail = (
        await client.patch(f"/automations/{created['id']}", json={"name": "Renamed"})
    ).json()
    assert detail["name"] == "Renamed"
    assert detail["document"]["name"] == "Renamed"


async def test_patch_toggles_enabled(client) -> None:
    created = await _create(client, name="Demo")
    detail = (
        await client.patch(f"/automations/{created['id']}", json={"enabled": False})
    ).json()
    assert detail["enabled"] is False
    rows = (await client.get("/automations")).json()
    assert rows[0]["enabled"] is False


async def test_delete_cascades_versions_runs_and_steps(client, session) -> None:
    created = await _create(client, document=document("Demo", [ai_step("step_fffff")]))
    aid = created["id"]
    await client.post(f"/automations/{aid}/runs", json={"trigger": "manual"})

    assert (await session.execute(select(RunStep))).scalars().all()

    resp = await client.delete(f"/automations/{aid}")
    assert resp.status_code == 204

    await session.rollback()  # re-read past this session's snapshot
    assert (await session.execute(select(Automation))).scalars().all() == []
    assert (await session.execute(select(Run))).scalars().all() == []
    assert (await session.execute(select(RunStep))).scalars().all() == []
    assert (await client.get(f"/automations/{aid}")).status_code == 404


# --- runs ------------------------------------------------------------------------------------


async def test_start_run_queues_it_with_pending_steps(client, session) -> None:
    created = await _create(
        client, document=document("Demo", [ai_step("step_ggggg"), ai_step("step_hhhhh")])
    )
    aid = created["id"]

    resp = await client.post(f"/automations/{aid}/runs", json={"trigger": "manual"})
    assert resp.status_code == 202
    run_id = resp.json()["runId"]

    detail = (await client.get(f"/automations/{aid}/runs/{run_id}")).json()
    assert detail["status"] == "queued"
    assert detail["trigger"] == "manual"
    assert detail["versionNumber"] == 1
    assert detail["inputTokens"] == 0
    assert [s["stepId"] for s in detail["steps"]] == ["step_ggggg", "step_hhhhh"]
    assert {s["status"] for s in detail["steps"]} == {"pending"}
    assert [s["index"] for s in detail["steps"]] == [0, 1]

    # The automation now points at its last run.
    rows = (await client.get("/automations")).json()
    assert rows[0]["lastRun"]["status"] == "queued"


async def test_second_start_while_one_is_in_flight_is_409(client) -> None:
    created = await _create(client, document=document("Demo", [ai_step("step_iiiii")]))
    aid = created["id"]

    assert (await client.post(f"/automations/{aid}/runs", json={})).status_code == 202
    conflict = await client.post(f"/automations/{aid}/runs", json={})
    assert conflict.status_code == 409
    assert conflict.json()["extra"]["runId"]


async def test_runs_list_is_newest_first_and_pageable(client) -> None:
    created = await _create(client, document=document("Demo", [ai_step("step_jjjjj")]))
    aid = created["id"]

    ids = []
    for _ in range(3):
        run_id = (await client.post(f"/automations/{aid}/runs", json={})).json()["runId"]
        ids.append(run_id)
        await client.post(f"/automations/{aid}/runs/{run_id}/cancel")

    listed = (await client.get(f"/automations/{aid}/runs")).json()
    assert [r["id"] for r in listed] == list(reversed(ids))
    assert listed[0]["versionNumber"] == 1

    page = (await client.get(f"/automations/{aid}/runs", params={"limit": 1})).json()
    assert len(page) == 1
    before = page[0]["createdAt"]
    older = (
        await client.get(f"/automations/{aid}/runs", params={"before": before})
    ).json()
    assert page[0]["id"] not in [r["id"] for r in older]


async def test_cancelling_a_queued_run_cancels_it_and_its_steps(client) -> None:
    created = await _create(client, document=document("Demo", [ai_step("step_kkkkk")]))
    aid = created["id"]
    run_id = (await client.post(f"/automations/{aid}/runs", json={})).json()["runId"]

    resp = await client.post(f"/automations/{aid}/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    detail = (await client.get(f"/automations/{aid}/runs/{run_id}")).json()
    assert detail["status"] == "cancelled"
    assert {s["status"] for s in detail["steps"]} == {"cancelled"}

    # Cancelling again is a no-op, and the automation can now be run afresh.
    assert (
        await client.post(f"/automations/{aid}/runs/{run_id}/cancel")
    ).json()["status"] == "cancelled"
    assert (await client.post(f"/automations/{aid}/runs", json={})).status_code == 202


async def test_a_run_from_another_automation_is_404(client) -> None:
    a = await _create(client, document=document("A", [ai_step("step_lllll")]))
    b = await _create(client, name="B")
    run_id = (await client.post(f"/automations/{a['id']}/runs", json={})).json()["runId"]

    assert (await client.get(f"/automations/{b['id']}/runs/{run_id}")).status_code == 404


@pytest.mark.parametrize("trigger", ["manual", "test"])
async def test_start_run_accepts_manual_and_test_triggers(client, trigger) -> None:
    created = await _create(client, name="Demo")
    resp = await client.post(f"/automations/{created['id']}/runs", json={"trigger": trigger})
    assert resp.status_code == 202


async def test_start_run_rejects_the_schedule_trigger(client) -> None:
    """Only the scheduler creates schedule runs; the API surface must not accept it."""
    created = await _create(client, name="Demo")
    resp = await client.post(
        f"/automations/{created['id']}/runs", json={"trigger": "schedule"}
    )
    assert resp.status_code == 422


# --- SSE ---------------------------------------------------------------------------------


async def test_events_stream_sends_a_snapshot_and_ends_for_a_finished_run(client) -> None:
    created = await _create(client, document=document("Demo", [ai_step("step_mmmmm")]))
    aid = created["id"]
    run_id = (await client.post(f"/automations/{aid}/runs", json={})).json()["runId"]
    await client.post(f"/automations/{aid}/runs/{run_id}/cancel")

    events = []
    async with client.stream("GET", f"/automations/{aid}/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))

    assert len(events) == 1
    assert events[0]["type"] == "snapshot"
    assert events[0]["run"]["id"] == run_id
    assert events[0]["run"]["status"] == "cancelled"
    assert [s["stepId"] for s in events[0]["run"]["steps"]] == ["step_mmmmm"]
