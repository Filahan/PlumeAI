"""End-to-end behavior of the builder assistant against a real database.

The provider is scripted: `app.llm.structured` imported `get_provider_for` by name, so
that binding is what gets replaced (patching `app.llm.factory` would not be seen). Every
reply the fake returns is a real `propose_changes` payload, schema-checked by
`complete_json` on the way through, so these tests exercise the same path a live model
does — including the self-correction turn after the document layer rejects a batch.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from app.db.models import Automation, Run, RunStep, UsageEntry
from app.llm.base import ChatMessage
from app.llm.events import AgentEvent
from app.services.assistant import REPLY_TOOL_NAME
from sqlalchemy import select


class ScriptedProvider:
    """Replays one scripted assistant reply per `stream_chat` call, recording the calls.

    The last script is repeated if called again, so a test that expects one call never
    fails with an IndexError instead of its actual assertion.
    """

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: Any = None,
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(
            {"model": model, "messages": list(messages), "tools": tools,
             "tool_choice": tool_choice}
        )
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return self._replay(reply)

    async def _replay(self, reply: dict[str, Any]) -> AsyncIterator[AgentEvent]:
        yield {
            "type": "tool_call",
            "id": "call_1",
            "tool": REPLY_TOOL_NAME,
            "args": json.dumps(reply),
        }
        yield {"type": "usage", "inputTokens": 120, "outputTokens": 40}


@pytest.fixture
def script(monkeypatch):
    """`script(reply, ...)` installs a fake provider and returns it for assertions."""

    def install(*replies: dict[str, Any]) -> ScriptedProvider:
        provider = ScriptedProvider(list(replies))

        async def fake_get_provider_for(session: Any, name: str) -> ScriptedProvider:
            provider.calls_provider_name = name  # type: ignore[attr-defined]
            return provider

        monkeypatch.setattr(
            "app.llm.structured.get_provider_for", fake_get_provider_for, raising=True
        )
        return provider

    return install


# --- reply builders ----------------------------------------------------------------------


def _ai_step(step_id: str, name: str, instructions: str = "Do the thing") -> dict[str, Any]:
    return {
        "id": step_id,
        "name": name,
        "type": "ai",
        "settings": {"instructions": instructions, "tools": [], "output": {"mode": "text"}},
    }


def _reply(
    message: str, operations: list[dict[str, Any]] | None = None, run_test: bool = False
) -> dict[str, Any]:
    return {"message": message, "operations": operations or [], "run_test": run_test}


async def _create(client, **body) -> dict:
    resp = await client.post("/automations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ask(client, automation_id: str, message: str = "add two steps") -> dict:
    resp = await client.post(f"/automations/{automation_id}/assistant", json={"message": message})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _row(session, automation_id: str) -> Automation:
    return (
        await session.execute(select(Automation).where(Automation.id == automation_id))
    ).scalar_one()


# --- a valid turn ------------------------------------------------------------------------

BUILD_REPLY = _reply(
    "I added a step that summarizes your mail and one that drafts a reply.",
    [
        {"op": "set_meta", "name": "Morning digest"},
        {"op": "add_step", "step": _ai_step("step_aaaaa", "Summarize the mail")},
        {
            "op": "add_step",
            "step": _ai_step("step_bbbbb", "Draft a reply", "Reply to {{step_aaaaa.output}}"),
        },
    ],
)


async def test_a_valid_turn_applies_the_operations_and_bumps_the_version(
    client, session, script
) -> None:
    provider = script(BUILD_REPLY)
    created = await _create(client, name="Untitled automation")

    body = await _ask(client, created["id"])

    assert body["error"] is None
    assert body["operationsApplied"] == 3
    assert body["message"].startswith("I added a step")
    assert body["versionNumber"] == created["versionNumber"] + 1
    assert body["summary"], "an applied edit must describe itself"
    assert [s["id"] for s in body["document"]["steps"]] == ["step_aaaaa", "step_bbbbb"]
    assert body["document"]["name"] == "Morning digest"
    assert body["issues"] == []
    assert body["runId"] is None
    assert len(provider.calls) == 1

    # The document really moved, and the version is attributed to the assistant.
    row = await _row(session, created["id"])
    assert row.name == "Morning digest"
    assert len(row.document["steps"]) == 2


async def test_a_valid_turn_persists_both_sides_of_the_conversation(
    client, session, script
) -> None:
    script(BUILD_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "summarize my mail then draft a reply")

    history = body["assistantMessages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "summarize my mail then draft a reply"
    assert history[1]["content"] == BUILD_REPLY["message"]
    assert history[1]["summary"] == body["summary"]
    assert history[1]["runId"] is None
    assert "error" not in history[1]
    assert all(isinstance(m["ts"], int) for m in history)

    # Persisted, not just returned — and visible to `GET /automations/{id}`.
    assert await _row(session, created["id"]) and len(
        (await _row(session, created["id"])).assistant_messages
    ) == 2
    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert len(detail["assistantMessages"]) == 2


async def test_the_turn_forces_the_reply_tool_and_sends_the_context(client, script) -> None:
    provider = script(BUILD_REPLY)
    created = await _create(client, name="Demo")

    await _ask(client, created["id"], "hello")

    call = provider.calls[0]
    assert call["tool_choice"] == {"type": "function", "function": {"name": REPLY_TOOL_NAME}}
    assert call["tools"][0]["function"]["name"] == REPLY_TOOL_NAME
    assert "$defs" in call["tools"][0]["function"]["parameters"]

    system = call["messages"][0]
    assert system.role == "system"
    assert "PlumeAI's automation assistant" in system.content
    assert "## The automation as it is right now" in system.content
    assert "## Integrations that are NOT connected" in system.content
    assert "never been run" in system.content
    assert call["messages"][-1].role == "user"
    assert call["messages"][-1].content == "hello"


async def test_the_turn_records_usage_against_the_automation(client, session, script) -> None:
    script(BUILD_REPLY)
    created = await _create(client, name="Demo")

    await _ask(client, created["id"])

    entries = (
        (await session.execute(select(UsageEntry).where(
            UsageEntry.conversation_id == created["id"]
        )))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].input_tokens == 120
    assert entries[0].output_tokens == 40


async def test_history_is_replayed_on_the_next_turn(client, script) -> None:
    provider = script(BUILD_REPLY, _reply("Anything else?"))
    created = await _create(client, name="Demo")

    await _ask(client, created["id"], "first question")
    await _ask(client, created["id"], "second question")

    replayed = [
        (m.role, m.content) for m in provider.calls[1]["messages"] if m.role != "system"
    ]
    assert replayed[0] == ("user", "first question")
    assert replayed[1] == ("assistant", BUILD_REPLY["message"])
    assert replayed[-1] == ("user", "second question")


# --- rejected operations -----------------------------------------------------------------

BAD_REPLY = _reply(
    "Renamed the step.",
    [{"op": "update_step", "step_id": "step_nope1", "patch": {"name": "Renamed"}}],
)


async def test_a_rejected_batch_is_retried_once_and_then_applied(
    client, session, script
) -> None:
    provider = script(BAD_REPLY, BUILD_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"])

    assert len(provider.calls) == 2
    assert body["error"] is None
    assert body["operationsApplied"] == 3
    assert [s["id"] for s in body["document"]["steps"]] == ["step_aaaaa", "step_bbbbb"]

    # The retry turn was told exactly what was wrong with the batch.
    retry = provider.calls[1]["messages"][-1]
    assert retry.role == "user"
    assert "rejected" in retry.content
    assert "step_nope1" in retry.content

    # Only the successful batch reached the transcript.
    history = (await _row(session, created["id"])).assistant_messages
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["content"] == BUILD_REPLY["message"]


async def test_twice_rejected_leaves_the_document_untouched_and_reports_the_error(
    client, session, script
) -> None:
    provider = script(BAD_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"])

    assert len(provider.calls) == 2  # the one automatic self-correction, and no more
    assert body["error"]
    assert "step_nope1" in body["error"]
    assert body["operationsApplied"] == 0
    assert body["summary"] == []
    assert body["document"]["steps"] == []
    assert body["versionNumber"] == created["versionNumber"]  # no version written
    # The user still gets an answer rather than an HTTP error.
    assert body["message"] == BAD_REPLY["message"]

    row = await _row(session, created["id"])
    assert row.document["steps"] == []
    # The failure is in the transcript, so the next turn can still see the mistake.
    assert row.assistant_messages[1]["error"] == body["error"]


async def test_a_rejected_batch_does_not_start_a_test_run(
    client, session, script, no_background_runs
) -> None:
    script({**BAD_REPLY, "run_test": True})
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "fix it and run it")

    assert body["error"]
    assert body["runId"] is None
    assert no_background_runs == []
    assert (await session.execute(select(Run))).scalars().all() == []


# --- test runs ---------------------------------------------------------------------------


async def test_run_test_queues_a_test_run_and_hands_it_to_the_executor(
    client, session, script, no_background_runs
) -> None:
    script(_reply("Running it now.", run_test=True))
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "run it")

    assert body["runId"]
    assert no_background_runs == [body["runId"]]

    run = (await session.execute(select(Run).where(Run.id == body["runId"]))).scalar_one()
    assert run.automation_id == created["id"]
    assert run.trigger == "test"
    assert run.status == "queued"
    # The run id is in the transcript too, so a reopened drawer can link to it.
    assert (await _row(session, created["id"])).assistant_messages[1]["runId"] == body["runId"]


async def test_run_test_with_a_run_already_in_flight_explains_itself(
    client, session, script, no_background_runs
) -> None:
    script(_reply("Running it now.", run_test=True))
    created = await _create(client, name="Demo")

    first = await client.post(f"/automations/{created['id']}/runs", json={"trigger": "manual"})
    assert first.status_code == 202

    body = await _ask(client, created["id"], "run it")

    assert body["runId"] is None
    assert body["error"] is None
    assert "already has a run in progress" in body["message"]
    # Nothing extra was queued.
    assert len((await session.execute(select(Run))).scalars().all()) == 1


async def test_run_test_applies_the_operations_before_running(
    client, session, script, no_background_runs
) -> None:
    script({**BUILD_REPLY, "run_test": True})
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "build it and test it")

    assert body["operationsApplied"] == 3
    assert body["runId"]
    # The run snapshotted the *new* version, so it has both steps to execute.
    run = (await session.execute(select(Run).where(Run.id == body["runId"]))).scalar_one()
    assert run.version_id == (await _row(session, created["id"])).current_version_id


# --- questions ---------------------------------------------------------------------------


async def test_a_question_only_reply_changes_nothing(client, session, script) -> None:
    script(_reply("It failed because Slack isn't connected yet."))
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "why did it fail?")

    assert body["error"] is None
    assert body["operationsApplied"] == 0
    assert body["summary"] == []
    assert body["versionNumber"] == created["versionNumber"]
    assert body["document"] == created["document"]
    # The exchange is still remembered.
    assert len((await _row(session, created["id"])).assistant_messages) == 2


async def test_the_last_run_failure_is_in_the_context(
    client, session, script, make_document, ai_step
) -> None:
    provider = script(_reply("Slack rejected the channel name."))
    created = await _create(
        client, document=make_document("Demo", [ai_step("step_aaaaa", "Post to Slack")])
    )

    # A finished, failed run with a failed step, as the executor would have left it.
    start = await client.post(f"/automations/{created['id']}/runs", json={"trigger": "test"})
    run_id = start.json()["runId"]
    await session.execute(
        Run.__table__.update()
        .where(Run.id == run_id)
        .values(status="failed", error="Step 'Post to Slack' failed")
    )
    await session.execute(
        RunStep.__table__.update()
        .where(RunStep.run_id == run_id)
        .values(
            status="failed",
            error="channel_not_found",
            trace=[{"event": "tool_error", "detail": "channel_not_found"}],
        )
    )
    await session.commit()

    await _ask(client, created["id"], "why did it fail?")

    system = provider.calls[0]["messages"][0].content
    assert "Most recent run: failed" in system
    assert "Step 'Post to Slack' failed" in system
    assert 'Failing step: "Post to Slack" (step_aaaaa) — channel_not_found' in system
    assert "tool_error" in system


# --- clearing ----------------------------------------------------------------------------


async def test_delete_clears_the_conversation_but_keeps_the_document(
    client, session, script
) -> None:
    script(BUILD_REPLY)
    created = await _create(client, name="Demo")
    await _ask(client, created["id"])

    resp = await client.delete(f"/automations/{created['id']}/assistant")
    assert resp.status_code == 204

    row = await _row(session, created["id"])
    assert row.assistant_messages == []
    assert len(row.document["steps"]) == 2  # the edits survive


# --- unknown automation ------------------------------------------------------------------


async def test_assistant_on_an_unknown_automation_is_404(client, script) -> None:
    script(BUILD_REPLY)
    assert (
        await client.post("/automations/nope/assistant", json={"message": "hi"})
    ).status_code == 404
    assert (await client.delete("/automations/nope/assistant")).status_code == 404


async def test_an_empty_message_is_rejected(client, script) -> None:
    script(BUILD_REPLY)
    created = await _create(client, name="Demo")
    resp = await client.post(f"/automations/{created['id']}/assistant", json={"message": ""})
    assert resp.status_code == 422
