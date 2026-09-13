"""Pure tests for the assistant's prompt: the reply schema and the context formatting.

Nothing here touches a database or a provider. The reply schema is the contract the LLM
is held to (`app.llm.structured` schema-checks the payload against it), and the context
block is the only thing standing between the model and inventing an integration — so
both are tested as data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.assistant import (
    ASSISTANT_REPLY_SCHEMA,
    MAX_FAILURE_DETAIL_CHARS,
    SYSTEM_PROMPT,
    FailedStepInfo,
    LastRunInfo,
    format_action,
    format_catalog,
    format_document,
    format_last_run,
    render_context,
)
from jsonschema import Draft202012Validator

# --- stubs -------------------------------------------------------------------------------
#
# Structurally what `app.services.catalog` returns (`CatalogAction` /
# `CatalogIntegration` / `Catalog`), reduced to the fields the prompt reads.


@dataclass
class StubAction:
    name: str
    integration: str
    label: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class StubIntegration:
    name: str
    label: str
    connected: bool
    actions: list[StubAction] = field(default_factory=list)


@dataclass
class StubCatalog:
    integrations: list[StubIntegration] = field(default_factory=list)
    builtin_actions: list[StubAction] = field(default_factory=list)


GMAIL_SEARCH = StubAction(
    name="gmail_search",
    integration="gmail",
    label="Search Gmail",
    description="Search for emails matching a query.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
            "scope": {"type": "string", "enum": ["inbox", "all"]},
        },
        "required": ["query"],
    },
)

NOTION_CREATE = StubAction(
    name="notion_create_page",
    integration="notion",
    label="Create Notion page",
    description="Create a page in a database.",
    input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
)

HTTP_REQUEST = StubAction(
    name="http_request",
    integration="builtin",
    label="HTTP request",
    description="Fetch a URL.",
    input_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
)


def _catalog() -> StubCatalog:
    return StubCatalog(
        integrations=[
            StubIntegration("gmail", "Gmail", True, [GMAIL_SEARCH]),
            StubIntegration("notion", "Notion", False, [NOTION_CREATE]),
        ],
        builtin_actions=[HTTP_REQUEST],
    )


DOCUMENT: dict[str, Any] = {
    "name": "Untitled automation",
    "description": "",
    "model": {"provider": "openai", "model": "gpt-4o-mini"},
    "trigger": {"type": "manual"},
    "steps": [
        {
            "id": "step_k3f9a",
            "name": "Summarize the mail",
            "type": "ai",
            "settings": {"instructions": "Summarize", "tools": [], "output": {"mode": "text"}},
        }
    ],
}


# --- the reply schema --------------------------------------------------------------------


def _validator() -> Draft202012Validator:
    return Draft202012Validator(ASSISTANT_REPLY_SCHEMA)


def test_reply_schema_is_a_valid_json_schema() -> None:
    # Both providers get this as a tool's `parameters`, and `complete_json` refuses a
    # schema that doesn't check out — so an unresolvable `$ref` has to fail here, loudly.
    Draft202012Validator.check_schema(ASSISTANT_REPLY_SCHEMA)


def test_reply_schema_hoists_the_operation_defs_to_the_top_level() -> None:
    assert "AddStep" in ASSISTANT_REPLY_SCHEMA["$defs"]
    assert "$defs" not in ASSISTANT_REPLY_SCHEMA["properties"]["operations"]["items"]


def test_reply_schema_accepts_a_full_reply() -> None:
    reply = {
        "message": "Added two steps.",
        "run_test": False,
        "operations": [
            {"op": "set_meta", "name": "Morning digest"},
            {
                "op": "add_step",
                "step": {
                    "id": "step_p2m7c",
                    "name": "Summarize the emails",
                    "type": "ai",
                    "settings": {
                        "instructions": "Summarize {{step_k3f9a.output}}",
                        "tools": [],
                        "output": {"mode": "text"},
                    },
                },
            },
            {"op": "update_step", "step_id": "step_k3f9a", "patch": {"name": "Find mail"}},
            {"op": "move_step", "step_id": "step_k3f9a", "index": 0},
            {"op": "remove_step", "step_id": "step_k3f9a"},
            {
                "op": "set_trigger",
                "trigger": {
                    "type": "schedule",
                    "settings": {"mode": "cron", "cron": "0 8 * * 1-5"},
                },
            },
        ],
    }
    assert list(_validator().iter_errors(reply)) == []


def test_reply_schema_requires_all_three_keys_and_nothing_else() -> None:
    v = _validator()
    assert list(v.iter_errors({"message": "hi", "operations": []}))  # no run_test
    assert list(v.iter_errors({"message": "hi", "run_test": False}))  # no operations
    assert list(v.iter_errors({"operations": [], "run_test": False}))  # no message
    assert list(v.iter_errors({"message": "hi", "operations": [], "run_test": False, "x": 1}))


def test_reply_schema_rejects_an_operation_with_no_op_discriminator() -> None:
    # `op` carries a Pydantic default, so the generated schema left it optional and the
    # `oneOf` was ambiguous; the assistant module adds it back as required.
    reply = {"message": "hi", "run_test": False, "operations": [{"name": "X"}]}
    assert list(_validator().iter_errors(reply))


def test_reply_schema_rejects_a_malformed_step() -> None:
    reply = {
        "message": "hi",
        "run_test": False,
        # `id` must match `step_[a-z0-9]{5,}` and `settings` is required.
        "operations": [{"op": "add_step", "step": {"id": "1", "name": "n", "type": "ai"}}],
    }
    assert list(_validator().iter_errors(reply))


# --- the system prompt -------------------------------------------------------------------


def test_system_prompt_covers_the_three_field_kinds_and_every_operation() -> None:
    for token in ("literal", "ref", "ai"):
        assert f'"kind":"{token}"' in SYSTEM_PROMPT
    for op in (
        "add_step",
        "update_step",
        "remove_step",
        "move_step",
        "set_trigger",
        "set_meta",
    ):
        assert op in SYSTEM_PROMPT
    # The rules the product depends on, spelled out.
    assert "not connected" in SYSTEM_PROMPT
    assert "run_test" in SYSTEM_PROMPT
    assert "120 words" in SYSTEM_PROMPT


# --- catalog formatting ------------------------------------------------------------------


def test_format_action_lists_types_enums_and_requiredness() -> None:
    line = format_action(GMAIL_SEARCH)
    assert line.startswith("- gmail.gmail_search — Search Gmail: Search for emails")
    assert "query (string, required)" in line
    assert "max_results (integer)" in line
    assert "scope (string, one of: inbox|all)" in line


def test_format_action_omits_the_verbose_schema() -> None:
    line = format_action(GMAIL_SEARCH)
    assert "properties" not in line
    assert "\n" not in line


def test_format_catalog_lists_connected_actions_and_builtins() -> None:
    text = format_catalog(_catalog())
    assert "gmail.gmail_search" in text
    assert "builtin.http_request" in text


def test_format_catalog_keeps_disconnected_actions_out_of_the_usable_list() -> None:
    text = format_catalog(_catalog())
    usable, _, rest = text.partition("## Integrations that are NOT connected")

    # The action itself must never appear as something the assistant may use…
    assert "notion_create_page" not in usable
    assert "notion_create_page" not in text
    # …but the integration is still named, with what the user has to do about it.
    assert "notion (Notion)" in rest
    assert "not connected (user must connect in Tools)" in rest


def test_format_catalog_says_so_when_nothing_is_connected() -> None:
    text = format_catalog(StubCatalog(integrations=[StubIntegration("gmail", "Gmail", False)]))
    assert "no integrations are connected yet" in text


def test_format_catalog_says_so_when_everything_is_connected() -> None:
    text = format_catalog(
        StubCatalog(integrations=[StubIntegration("gmail", "Gmail", True, [GMAIL_SEARCH])])
    )
    assert "every integration is connected" in text


# --- document + last-run formatting ------------------------------------------------------


def test_format_document_renders_the_document_json() -> None:
    text = format_document(DOCUMENT)
    assert "step_k3f9a" in text
    assert '"type": "ai"' in text


def test_format_document_clips_a_huge_document() -> None:
    text = format_document({"blob": "x" * 50_000})
    assert text.endswith("…[truncated]")
    assert len(text) < 20_000


def test_format_last_run_explains_the_failure() -> None:
    text = format_last_run(
        LastRunInfo(
            run_id="run_1",
            status="failed",
            trigger="test",
            error="Step 'Post to Slack' failed",
            failed_step=FailedStepInfo(
                step_id="step_z5r2b",
                name="Post to Slack",
                error="channel_not_found",
                detail='[{"event":"tool_error","detail":"channel_not_found"}]',
            ),
        )
    )
    assert "failed" in text
    assert "Post to Slack" in text
    assert "step_z5r2b" in text
    assert "channel_not_found" in text
    assert "tool_error" in text


def test_format_last_run_clips_the_failure_detail() -> None:
    text = format_last_run(
        LastRunInfo(
            run_id="run_1",
            status="failed",
            failed_step=FailedStepInfo(step_id="step_a", name="A", detail="y" * 5_000),
        )
    )
    assert "…[truncated]" in text
    assert len(text) < MAX_FAILURE_DETAIL_CHARS + 500


def test_format_last_run_handles_never_run() -> None:
    assert "never been run" in format_last_run(None)


# --- the whole context block -------------------------------------------------------------


def test_render_context_carries_date_document_catalog_and_last_run() -> None:
    text = render_context(
        document=DOCUMENT,
        catalog=_catalog(),
        today="2026-09-13 (Sunday)",
        now="08:30",
        timezone_name="Europe/Paris",
        last_run=LastRunInfo(
            run_id="run_1",
            status="failed",
            failed_step=FailedStepInfo(step_id="step_k3f9a", name="Summarize the mail",
                                       error="boom"),
        ),
    )
    assert "2026-09-13 (Sunday)" in text
    assert "Europe/Paris" in text
    assert "08:30" in text
    assert "step_k3f9a" in text          # the document
    assert "gmail.gmail_search" in text  # the catalog
    assert "notion" in text              # the disconnected integration
    assert "boom" in text                # the last run's failure
