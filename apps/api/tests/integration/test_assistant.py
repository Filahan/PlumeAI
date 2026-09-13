"""End-to-end behavior of the builder assistant against a real database.

The provider is scripted: `app.llm.structured` imported `get_provider_for` by name, so
that binding is what gets replaced (patching `app.llm.factory` would not be seen). Every
reply the fake returns is a real `propose_changes` payload, schema-checked by
`complete_json` on the way through, so these tests exercise the same path a live model
does — including both self-correction routes (a batch the document layer refused, and a
batch that applied but left the automation unrunnable).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Automation, Run, RunStep, UsageEntry
from app.errors import ProviderError
from app.llm.base import ChatMessage
from app.llm.events import AgentEvent
from app.services import assistant as assistant_svc
from app.services import automations as automations_svc
from app.services.assistant import (
    CORRECTION_FAILED_CAVEAT,
    ISSUES_CAVEAT,
    REJECTED_ERROR,
    UNREADABLE_DOCUMENT_ERROR,
)
from app.services.assistant_prompt import REPLY_TOOL_NAME, UNTRUSTED_OPEN


class ScriptedProvider:
    """Replays one scripted assistant reply per `stream_chat` call, recording the calls.

    A script entry that is an exception is raised instead of replayed, which is how the
    provider-failure paths are exercised. The last entry repeats if called again, so a
    test that expects one call fails with its own assertion rather than an IndexError.
    """

    def __init__(self, replies: list[Any]) -> None:
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
        entry = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return self._replay(entry)

    async def _replay(self, entry: Any) -> AsyncIterator[AgentEvent]:
        if isinstance(entry, BaseException):
            raise entry
        yield {
            "type": "tool_call",
            "id": "call_1",
            "tool": REPLY_TOOL_NAME,
            "args": json.dumps(entry),
        }
        yield {"type": "usage", "inputTokens": 120, "outputTokens": 40}


@pytest.fixture
def script(monkeypatch):
    """`script(reply, ...)` installs a fake provider and returns it for assertions."""

    def install(*replies: Any) -> ScriptedProvider:
        provider = ScriptedProvider(list(replies))

        async def fake_get_provider_for(session: Any, name: str) -> ScriptedProvider:
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


def _edit(message: str, operations: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"intent": "edit", "message": message, "operations": operations, **extra}


def _answer(message: str, **extra: Any) -> dict[str, Any]:
    """An answer turn as a model actually writes it: no `operations`, no `run_test`."""
    return {"intent": "answer", "message": message, **extra}


BUILD_REPLY = _edit(
    "I added a step that summarizes your mail and one that drafts a reply.",
    [
        {"op": "set_meta", "name": "Morning digest"},
        {"op": "add_step", "step": _ai_step("step_aaaaa", "Summarize the mail")},
        {
            "op": "add_step",
            "step": _ai_step("step_bbbbb", "Draft a reply", "Reply to {{step_aaaaa.output}}"),
        },
    ],
    run_test=False,
)

# Refused by `apply_operations` outright: nothing is written.
BAD_REPLY = _edit(
    "Renamed the step.",
    [{"op": "update_step", "step_id": "step_nope1", "patch": {"name": "Renamed"}}],
)

# Applies cleanly, but leaves an error-level validation issue: the instructions point at
# a step that does not exist.
DANGLING_REF_REPLY = _edit(
    "Added a summary step.",
    [{"op": "add_step", "step": _ai_step("step_ccccc", "Summarize",
                                        "Summarize {{step_zzzzz.output}}")}],
)
STILL_DANGLING_REPLY = _edit(
    "Tried again.",
    [
        {
            "op": "update_step",
            "step_id": "step_ccccc",
            "patch": {"settings": {"instructions": "Summarize {{step_yyyyy.output}}"}},
        }
    ],
)
FIXED_REF_REPLY = _edit(
    "Fixed the summary step.",
    [
        {
            "op": "update_step",
            "step_id": "step_ccccc",
            "patch": {"settings": {"instructions": "Summarize today's mail"}},
        }
    ],
)


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


async def test_a_valid_turn_applies_the_operations_and_bumps_the_version(
    client, session, script
) -> None:
    provider = script(BUILD_REPLY)
    created = await _create(client, name="Untitled automation")

    body = await _ask(client, created["id"])

    assert body["error"] is None
    assert body["operationsApplied"] == 3
    assert body["message"] == BUILD_REPLY["message"]
    assert body["versionNumber"] == created["versionNumber"] + 1
    assert body["summary"], "an applied edit must describe itself"
    assert [s["id"] for s in body["document"]["steps"]] == ["step_aaaaa", "step_bbbbb"]
    assert body["document"]["name"] == "Morning digest"
    assert body["issues"] == []
    assert body["runId"] is None
    assert len(provider.calls) == 1

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

    assert len((await _row(session, created["id"])).assistant_messages) == 2
    detail = (await client.get(f"/automations/{created['id']}")).json()
    assert len(detail["assistantMessages"]) == 2


async def test_the_turn_forces_the_reply_tool_and_splits_rules_from_context(
    client, script
) -> None:
    provider = script(BUILD_REPLY)
    created = await _create(client, name="Demo")

    await _ask(client, created["id"], "hello")

    call = provider.calls[0]
    assert call["tool_choice"] == {"type": "function", "function": {"name": REPLY_TOOL_NAME}}
    assert call["tools"][0]["function"]["name"] == REPLY_TOOL_NAME
    assert "$defs" in call["tools"][0]["function"]["parameters"]

    system, context = call["messages"][0], call["messages"][1]
    assert system.role == "system"
    assert "PlumeAI's automation assistant" in system.content
    assert "# Actions you may use" in system.content
    # The automation and its run history are a *user* message, not part of the rules.
    assert "# Context" not in system.content
    assert context.role == "user"
    assert "## The automation as it is right now" in context.content
    assert "never been run" in context.content

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
    assert entries[0].source == "assistant"


async def test_history_is_replayed_on_the_next_turn(client, script) -> None:
    provider = script(BUILD_REPLY, _answer("Anything else?"))
    created = await _create(client, name="Demo")

    await _ask(client, created["id"], "first question")
    await _ask(client, created["id"], "second question")

    replayed = [
        (m.role, m.content) for m in provider.calls[1]["messages"] if m.role != "system"
    ]
    assert replayed[0][0] == "user" and "# Context" in replayed[0][1]
    assert replayed[1] == ("user", "first question")
    assert replayed[2] == ("assistant", BUILD_REPLY["message"])
    assert replayed[-1] == ("user", "second question")


# --- the intent guard --------------------------------------------------------------------


async def test_an_answer_turn_that_returned_operations_has_them_dropped(
    client, session, script
) -> None:
    # The model said it was answering a question and edited anyway. The stated intent
    # wins: a question must never move the document.
    script({**BUILD_REPLY, "intent": "answer"})
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "what does this do?")

    assert body["operationsApplied"] == 0
    assert body["summary"] == []
    assert body["error"] is None
    assert body["versionNumber"] == created["versionNumber"]
    assert body["document"] == created["document"]
    assert (await _row(session, created["id"])).document["steps"] == []


async def test_an_edit_turn_with_the_same_operations_applies_them(client, script) -> None:
    script(BUILD_REPLY)
    created = await _create(client, name="Demo")
    body = await _ask(client, created["id"], "add the steps")
    assert body["operationsApplied"] == 3


async def test_a_reply_that_omits_operations_and_run_test_is_a_clean_answer(
    client, session, script
) -> None:
    # The C1 regression, end to end: a model that omits `run_test`/`operations` (the
    # normal shape of an answer) used to fail the schema and 502 the request.
    provider = script(_answer("It failed because Slack isn't connected yet."))
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "why did it fail?")

    assert len(provider.calls) == 1
    assert body["error"] is None
    assert body["operationsApplied"] == 0
    assert body["runId"] is None
    assert body["versionNumber"] == created["versionNumber"]
    assert body["document"] == created["document"]
    assert len((await _row(session, created["id"])).assistant_messages) == 2


# --- rejected operations -----------------------------------------------------------------


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


async def test_twice_rejected_leaves_the_document_untouched_and_reports_a_fixed_error(
    client, session, script
) -> None:
    provider = script(BAD_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"])

    assert len(provider.calls) == 2  # the one automatic self-correction, and no more
    # The client is told something it can act on — never the raw rejection text, which
    # can quote the model's payload.
    assert body["error"] == REJECTED_ERROR
    assert "step_nope1" not in json.dumps(body)
    assert body["operationsApplied"] == 0
    assert body["summary"] == []
    assert body["document"]["steps"] == []
    assert body["versionNumber"] == created["versionNumber"]
    assert body["message"] == BAD_REPLY["message"]

    row = await _row(session, created["id"])
    assert row.document["steps"] == []
    assert row.assistant_messages[1]["error"] == REJECTED_ERROR


async def test_a_rejected_turn_is_replayed_as_a_failure_on_the_next_turn(
    client, script
) -> None:
    provider = script(BAD_REPLY, BAD_REPLY, _answer("Sorry about that."))
    created = await _create(client, name="Demo")

    await _ask(client, created["id"])
    await _ask(client, created["id"], "try again")

    replayed = [m.content for m in provider.calls[2]["messages"] if m.role == "assistant"]
    assert replayed
    assert assistant_svc.HISTORY_REJECTION_NOTE in replayed[-1]
    # Still without the raw rejection text.
    assert "step_nope1" not in replayed[-1]


async def test_a_rejected_batch_does_not_start_a_test_run(
    client, session, script, no_background_runs
) -> None:
    script({**BAD_REPLY, "run_test": True})
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "fix it and run it")

    assert body["error"] == REJECTED_ERROR
    assert body["runId"] is None
    assert no_background_runs == []
    assert (await session.execute(select(Run))).scalars().all() == []


# --- operations that apply but leave the automation broken -------------------------------


async def test_error_level_issues_trigger_one_self_correction(client, session, script) -> None:
    provider = script(DANGLING_REF_REPLY, FIXED_REF_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "summarize my mail")

    assert len(provider.calls) == 2
    assert body["error"] is None
    assert body["issues"] == []
    assert ISSUES_CAVEAT not in body["message"]
    assert body["message"] == FIXED_REF_REPLY["message"]
    assert body["document"]["steps"][0]["settings"]["instructions"] == "Summarize today's mail"
    assert body["document"]["steps"][0]["valid"] is True

    # Both batches were the user's one edit, so both are reported as one.
    assert body["operationsApplied"] == 2
    assert body["summary"] == ["Added step 'Summarize'", "Updated step 'Summarize'"]
    assert body["versionNumber"] == created["versionNumber"] + 2

    # The correction turn was given the issues *and* the document as it stood.
    correction = provider.calls[1]["messages"][-1]
    assert correction.role == "user"
    assert "reference to unknown step" in correction.content
    assert "step_zzzzz" in correction.content
    assert "Here is the automation as it stands now" in correction.content
    assert "1. step_ccccc" in correction.content

    row = await _row(session, created["id"])
    assert row.valid is True
    assert row.assistant_messages[1]["summary"] == body["summary"]


async def test_issues_that_survive_an_applied_correction_are_flagged_in_the_message(
    client, session, script
) -> None:
    # The correction applied and still left the reference dangling. The edit stands (it
    # is versioned and visible), but the user is told it needs attention.
    provider = script(DANGLING_REF_REPLY, STILL_DANGLING_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "summarize my mail")

    assert len(provider.calls) == 2
    assert body["error"] is None  # something *was* applied
    assert body["message"] == f"{STILL_DANGLING_REPLY['message']} {ISSUES_CAVEAT}"
    assert [i["level"] for i in body["issues"]] == ["error"]
    assert body["operationsApplied"] == 2
    assert body["document"]["steps"][0]["valid"] is False

    row = await _row(session, created["id"])
    assert row.valid is False
    assert len(row.document["steps"]) == 1


async def test_a_rejected_correction_keeps_the_message_of_the_edit_that_landed(
    client, session, script
) -> None:
    # The correction turn repeats the same `add_step`, which is refused (duplicate id).
    # The first batch is still on the document, so its message is what describes the
    # automation — the refused turn described work that does not exist.
    provider = script(DANGLING_REF_REPLY)
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "summarize my mail")

    assert len(provider.calls) == 2
    assert body["error"] is None  # something *was* applied
    assert body["message"] == f"{DANGLING_REF_REPLY['message']} {CORRECTION_FAILED_CAVEAT}"
    assert ISSUES_CAVEAT not in body["message"]
    assert body["operationsApplied"] == 1
    assert body["summary"] == ["Added step 'Summarize'"]
    assert [i["level"] for i in body["issues"]] == ["error"]
    assert body["versionNumber"] == created["versionNumber"] + 1

    row = await _row(session, created["id"])
    assert row.valid is False
    assert len(row.document["steps"]) == 1
    assert row.assistant_messages[1]["content"] == body["message"]


# --- test runs ---------------------------------------------------------------------------


async def test_run_test_queues_a_test_run_and_hands_it_to_the_executor(
    client, session, script, no_background_runs
) -> None:
    script(_answer("Running it now.", run_test=True))
    created = await _create(client, name="Demo")

    body = await _ask(client, created["id"], "run it")

    assert body["runId"]
    assert no_background_runs == [body["runId"]]

    run = (await session.execute(select(Run).where(Run.id == body["runId"]))).scalar_one()
    assert run.automation_id == created["id"]
    assert run.trigger == "test"
    assert run.status == "queued"
    assert (await _row(session, created["id"])).assistant_messages[1]["runId"] == body["runId"]


async def test_run_test_with_a_run_already_in_flight_explains_itself(
    client, session, script, no_background_runs
) -> None:
    script(_answer("Running it now.", run_test=True))
    created = await _create(client, name="Demo")

    first = await client.post(f"/automations/{created['id']}/runs", json={"trigger": "manual"})
    assert first.status_code == 202

    body = await _ask(client, created["id"], "run it")

    assert body["runId"] is None
    assert body["error"] is None
    assert "already has a run in progress" in body["message"]
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


# --- the last run, as untrusted context --------------------------------------------------


async def test_the_last_run_failure_reaches_the_context_fenced_as_untrusted(
    client, session, script, make_document, ai_step
) -> None:
    provider = script(_answer("Slack rejected the channel name."))
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

    context = provider.calls[0]["messages"][1].content
    assert "Most recent run: failed" in context
    assert "Step 'Post to Slack' failed" in context
    assert 'Failing step: "Post to Slack" (step_aaaaa)' in context
    assert "Step error: channel_not_found" in context
    # The raw trace is summarized by shape, inside the untrusted fence.
    assert UNTRUSTED_OPEN in context
    assert 'Shape of what that step recorded: [1 items: {event: "tool_error"' in context


# --- an unreadable draft -----------------------------------------------------------------


async def test_an_unparseable_document_is_answered_without_calling_the_model(
    client, session, script
) -> None:
    provider = script(BUILD_REPLY)
    created = await _create(client, name="Demo")
    await session.execute(
        Automation.__table__.update()
        .where(Automation.id == created["id"])
        .values(document={"name": "broken"})
    )
    await session.commit()

    body = await _ask(client, created["id"], "add a step")

    assert provider.calls == []  # nothing was spent
    assert body["error"] == UNREADABLE_DOCUMENT_ERROR
    assert body["message"] == UNREADABLE_DOCUMENT_ERROR
    assert body["operationsApplied"] == 0
    assert body["document"] == {"name": "broken"}
    # The exchange is still recorded, so the drawer shows the answer.
    assert len((await _row(session, created["id"])).assistant_messages) == 2


# --- provider failures -------------------------------------------------------------------


async def test_a_provider_failure_leaves_the_transcript_and_document_untouched(
    client, session, script
) -> None:
    script(ProviderError("upstream is down", extra={"reason": "upstream"}))
    created = await _create(client, name="Demo")

    resp = await client.post(
        f"/automations/{created['id']}/assistant", json={"message": "add a step"}
    )
    assert resp.status_code == 502

    row = await _row(session, created["id"])
    assert row.assistant_messages == []
    assert row.document == created["document"]


async def test_a_provider_failure_on_the_correction_turn_rolls_the_turn_back(
    client, session, script
) -> None:
    script(BAD_REPLY, ProviderError("upstream is down", extra={"reason": "upstream"}))
    created = await _create(client, name="Demo")

    resp = await client.post(
        f"/automations/{created['id']}/assistant", json={"message": "rename the step"}
    )
    assert resp.status_code == 502

    row = await _row(session, created["id"])
    assert row.assistant_messages == []
    assert row.document == created["document"]


async def test_tokens_already_spent_are_recorded_even_when_the_turn_fails(
    session, script
) -> None:
    # Called at the service level: over HTTP the request dependency rolls the failed turn
    # back, so this is the only place the `finally` is observable.
    script(BAD_REPLY, ProviderError("upstream is down", extra={"reason": "upstream"}))
    automation = await automations_svc.create_automation(session, name="Demo")

    with pytest.raises(ProviderError):
        await assistant_svc.chat(session, automation, "rename the step")

    await session.commit()
    entries = (
        (await session.execute(select(UsageEntry).where(
            UsageEntry.conversation_id == automation.id
        )))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].input_tokens == 120


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


# --- request validation ------------------------------------------------------------------


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
