"""Tests for the automation document language: schemas, operations, validation, diffing.

Pure functions and models only — no network, no DB.
"""

from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.documents import (
    ActionSettings,
    ActionStep,
    AddStep,
    AiOutput,
    AiStep,
    AiStepSettings,
    AutomationDocument,
    Condition,
    FieldValue,
    FilterSettings,
    FilterStep,
    ManualTrigger,
    ModelRef,
    MoveStep,
    Operation,
    RemoveStep,
    RetryPolicy,
    Rules,
    ScheduleSettings,
    ScheduleTrigger,
    SetMeta,
    SetTrigger,
    UpdateStep,
)
from app.services.documents import (
    ActionMeta,
    apply_operations,
    diff_summary,
    describe_trigger,
    dump_document,
    new_step_id,
    validate_document,
)

from conftest import StubCatalog

# --- round trip --------------------------------------------------------------------------


def test_example_document_round_trips_unchanged(example_document_json: dict) -> None:
    doc = AutomationDocument.model_validate(example_document_json)
    dumped = doc.model_dump(by_alias=True, exclude_none=True)
    assert dumped == example_document_json
    assert dumped == dump_document(doc)


def test_example_document_round_trips_exact_json_text(example_document_json: dict) -> None:
    """Dict equality alone can hide type drift (e.g. `10.0 == 10` in Python). Compare the
    *serialized JSON text* instead, so an int-vs-float (or str-vs-int, etc.) regression on
    any field is caught even when the values look "equal" in Python.
    """
    doc = AutomationDocument.model_validate(example_document_json)
    actual_text = doc.model_dump_json(by_alias=True, exclude_none=True)
    actual_sorted = json.dumps(json.loads(actual_text), sort_keys=True)
    expected_sorted = json.dumps(example_document_json, sort_keys=True)
    assert actual_sorted == expected_sorted

    # In particular: retry.backoff_seconds must serialize as an integer, not 10.0.
    assert '"backoff_seconds":10' in actual_text.replace(" ", "")
    assert '"backoff_seconds":10.0' not in actual_text.replace(" ", "")


def test_example_document_parses_into_expected_types(example_document_json: dict) -> None:
    doc = AutomationDocument.model_validate(example_document_json)
    assert isinstance(doc.trigger, ScheduleTrigger)
    assert isinstance(doc.steps[0], ActionStep)
    assert isinstance(doc.steps[1], AiStep)
    assert isinstance(doc.steps[2], FilterStep)
    assert isinstance(doc.steps[3], ActionStep)
    assert doc.steps[0].settings.input["query"].kind == "ai"
    assert doc.steps[0].settings.input["max_results"].value == 20


# --- FieldValue validation -----------------------------------------------------------------


def test_field_value_ref_requires_template_shape() -> None:
    FieldValue(kind="ref", value="{{step_abc12.output}}")  # ok
    FieldValue(kind="ref", value="{{ step_abc12.output.items[0] }}")  # ok, with spaces
    with pytest.raises(ValidationError):
        FieldValue(kind="ref", value="step_abc12.output")  # missing braces
    with pytest.raises(ValidationError):
        FieldValue(kind="ref", value="{{}}")


def test_field_value_ai_requires_non_empty_string() -> None:
    FieldValue(kind="ai", value="Find the total")
    with pytest.raises(ValidationError):
        FieldValue(kind="ai", value="")
    with pytest.raises(ValidationError):
        FieldValue(kind="ai", value=123)


def test_field_value_literal_accepts_any_value() -> None:
    assert FieldValue(kind="literal", value=5).value == 5
    assert FieldValue(kind="literal", value=None).value is None
    assert FieldValue(kind="literal", value=[1, 2]).value == [1, 2]


# --- other schema validators ---------------------------------------------------------------


def test_step_id_pattern_enforced() -> None:
    with pytest.raises(ValidationError):
        ActionStep(
            id="bad-id",
            name="x",
            settings=ActionSettings(integration="gmail", action="gmail_search"),
        )


def test_automation_document_rejects_duplicate_step_ids() -> None:
    step = ActionStep(
        id="step_aaaaa",
        name="x",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    with pytest.raises(ValidationError):
        AutomationDocument(
            name="d",
            model=ModelRef(provider="openai", model="gpt-4o-mini"),
            trigger=ManualTrigger(),
            steps=[step, step.model_copy()],
        )


def test_schedule_settings_cron_mode_requires_valid_cron() -> None:
    ScheduleSettings(mode="cron", cron="0 8 * * 1-5")
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="cron", cron=None)
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="cron", cron="not a cron")


def test_schedule_settings_interval_mode_requires_every_minutes() -> None:
    ScheduleSettings(mode="interval", every_minutes=15)
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="interval")


def test_schedule_settings_rejects_unknown_timezone() -> None:
    ScheduleSettings(mode="cron", cron="0 8 * * *", timezone="Europe/Paris")
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="cron", cron="0 8 * * *", timezone="Not/AZone")


def test_schedule_settings_every_minutes_bounds() -> None:
    ScheduleSettings(mode="interval", every_minutes=1)  # lower bound ok
    ScheduleSettings(mode="interval", every_minutes=10080)  # upper bound ok
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="interval", every_minutes=0)
    with pytest.raises(ValidationError):
        ScheduleSettings(mode="interval", every_minutes=10081)


def test_retry_policy_bounds() -> None:
    RetryPolicy(max_attempts=1, backoff_seconds=0)  # lower bounds ok
    RetryPolicy(max_attempts=10, backoff_seconds=300)  # upper bounds ok
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=11)
    with pytest.raises(ValidationError):
        RetryPolicy(backoff_seconds=-1)
    with pytest.raises(ValidationError):
        RetryPolicy(backoff_seconds=301)


def test_retry_policy_backoff_seconds_serializes_as_int() -> None:
    policy = RetryPolicy(max_attempts=3, backoff_seconds=10)
    assert isinstance(policy.backoff_seconds, int)
    dumped = policy.model_dump(by_alias=True)
    assert dumped["backoff_seconds"] == 10
    assert isinstance(dumped["backoff_seconds"], int)
    assert '"backoff_seconds":10' in policy.model_dump_json(by_alias=True).replace(" ", "")


def test_filter_settings_requires_matching_field_for_mode() -> None:
    FilterSettings(
        mode="rules",
        rules=Rules(
            conditions=[
                Condition(
                    left=FieldValue(kind="literal", value=1),
                    op="gt",
                    right=FieldValue(kind="literal", value=0),
                )
            ]
        ),
    )
    FilterSettings(mode="ai", instruction="Only continue if urgent")
    with pytest.raises(ValidationError):
        FilterSettings(mode="rules")
    with pytest.raises(ValidationError):
        FilterSettings(mode="ai")


def test_ai_output_schema_field_uses_schema_alias() -> None:
    out = AiOutput.model_validate({"mode": "json", "schema": {"type": "object"}})
    assert out.schema_ == {"type": "object"}
    assert out.model_dump(by_alias=True)["schema"] == {"type": "object"}


# --- apply_operations ----------------------------------------------------------------------


def _basic_doc() -> AutomationDocument:
    return AutomationDocument(
        name="Basic",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="First",
                settings=ActionSettings(integration="gmail", action="gmail_search"),
            ),
            ActionStep(
                id="step_bbbbb",
                name="Second",
                settings=ActionSettings(integration="slack", action="slack_send_message"),
            ),
        ],
    )


def test_new_step_id_shape() -> None:
    sid = new_step_id()
    assert sid.startswith("step_")
    assert len(sid) == len("step_") + 6
    assert new_step_id() != new_step_id()


def test_add_step_appends_without_index() -> None:
    doc = _basic_doc()
    new_step = ActionStep(
        id="step_ccccc",
        name="Third",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    new_doc = apply_operations(doc, [AddStep(step=new_step)])
    assert [s.id for s in new_doc.steps] == ["step_aaaaa", "step_bbbbb", "step_ccccc"]
    assert [s.id for s in doc.steps] == ["step_aaaaa", "step_bbbbb"]  # original untouched


def test_add_step_with_index_inserts() -> None:
    doc = _basic_doc()
    new_step = ActionStep(
        id="step_ccccc",
        name="Third",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    new_doc = apply_operations(doc, [AddStep(step=new_step, index=1)])
    assert [s.id for s in new_doc.steps] == ["step_aaaaa", "step_ccccc", "step_bbbbb"]


def test_add_step_duplicate_id_raises() -> None:
    doc = _basic_doc()
    dup = ActionStep(
        id="step_aaaaa",
        name="Dup",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    with pytest.raises(ValueError, match="already exists"):
        apply_operations(doc, [AddStep(step=dup)])


def test_add_step_bad_index_raises() -> None:
    doc = _basic_doc()
    new_step = ActionStep(
        id="step_ccccc",
        name="Third",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    with pytest.raises(ValueError, match="index out of range"):
        apply_operations(doc, [AddStep(step=new_step, index=99)])


def test_update_step_shallow_merges_top_level_fields() -> None:
    doc = _basic_doc()
    new_doc = apply_operations(
        doc, [UpdateStep(step_id="step_aaaaa", patch={"name": "Renamed"})]
    )
    assert new_doc.steps[0].name == "Renamed"
    assert new_doc.steps[0].settings.action == "gmail_search"  # untouched


def test_update_step_replaces_settings_wholesale() -> None:
    doc = _basic_doc()
    new_doc = apply_operations(
        doc,
        [
            UpdateStep(
                step_id="step_aaaaa",
                patch={"settings": {"integration": "slack", "action": "slack_send_message"}},
            )
        ],
    )
    updated = new_doc.steps[0]
    assert updated.settings.integration == "slack"
    assert updated.settings.action == "slack_send_message"
    assert updated.settings.input == {}


def test_update_step_unknown_id_raises() -> None:
    doc = _basic_doc()
    with pytest.raises(ValueError, match="unknown step id"):
        apply_operations(doc, [UpdateStep(step_id="step_zzzzz", patch={"name": "x"})])


def test_update_step_patch_making_step_invalid_raises() -> None:
    doc = _basic_doc()
    # "id" no longer matches the step id pattern -> the patched step fails Step validation.
    with pytest.raises(ValidationError):
        apply_operations(doc, [UpdateStep(step_id="step_aaaaa", patch={"id": "not-a-valid-id"})])


def test_update_step_patch_with_missing_required_settings_field_raises() -> None:
    doc = _basic_doc()
    # Replacing settings wholesale but dropping the required "action" key.
    with pytest.raises(ValidationError):
        apply_operations(
            doc,
            [UpdateStep(step_id="step_aaaaa", patch={"settings": {"integration": "gmail"}})],
        )


def test_remove_step() -> None:
    doc = _basic_doc()
    new_doc = apply_operations(doc, [RemoveStep(step_id="step_aaaaa")])
    assert [s.id for s in new_doc.steps] == ["step_bbbbb"]


def test_remove_step_unknown_id_raises() -> None:
    doc = _basic_doc()
    with pytest.raises(ValueError, match="unknown step id"):
        apply_operations(doc, [RemoveStep(step_id="step_zzzzz")])


def test_move_step() -> None:
    doc = _basic_doc()
    new_doc = apply_operations(doc, [MoveStep(step_id="step_bbbbb", index=0)])
    assert [s.id for s in new_doc.steps] == ["step_bbbbb", "step_aaaaa"]


def test_move_step_bad_index_raises() -> None:
    doc = _basic_doc()
    with pytest.raises(ValueError, match="index out of range"):
        apply_operations(doc, [MoveStep(step_id="step_bbbbb", index=99)])


def test_set_trigger() -> None:
    doc = _basic_doc()
    new_trigger = ScheduleTrigger(settings=ScheduleSettings(mode="interval", every_minutes=30))
    new_doc = apply_operations(doc, [SetTrigger(trigger=new_trigger)])
    assert isinstance(new_doc.trigger, ScheduleTrigger)
    assert new_doc.trigger.settings.every_minutes == 30
    assert isinstance(doc.trigger, ManualTrigger)  # original untouched


def test_set_meta_updates_only_given_fields() -> None:
    doc = _basic_doc()
    new_doc = apply_operations(doc, [SetMeta(description="new description")])
    assert new_doc.name == "Basic"  # unchanged
    assert new_doc.description == "new description"
    assert new_doc.model.provider == "openai"


def test_apply_operations_applies_in_order() -> None:
    doc = _basic_doc()
    new_step = ActionStep(
        id="step_ccccc",
        name="Third",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    new_doc = apply_operations(
        doc,
        [
            AddStep(step=new_step),
            MoveStep(step_id="step_ccccc", index=0),
            RemoveStep(step_id="step_bbbbb"),
        ],
    )
    assert [s.id for s in new_doc.steps] == ["step_ccccc", "step_aaaaa"]


# --- Operation discriminator ----------------------------------------------------------------

_OPERATION_ADAPTER: TypeAdapter[Operation] = TypeAdapter(Operation)

_SAMPLE_STEP_DICT = {
    "id": "step_aaaaa",
    "name": "Search",
    "type": "action",
    "settings": {"integration": "gmail", "action": "gmail_search", "input": {}},
    "valid": True,
}

_SAMPLE_TRIGGER_DICT = {"type": "manual"}


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"op": "add_step", "step": _SAMPLE_STEP_DICT, "index": None}, AddStep),
        ({"op": "update_step", "step_id": "step_aaaaa", "patch": {"name": "x"}}, UpdateStep),
        ({"op": "remove_step", "step_id": "step_aaaaa"}, RemoveStep),
        ({"op": "move_step", "step_id": "step_aaaaa", "index": 0}, MoveStep),
        ({"op": "set_trigger", "trigger": _SAMPLE_TRIGGER_DICT}, SetTrigger),
        ({"op": "set_meta", "name": "New name"}, SetMeta),
    ],
)
def test_operation_discriminator_resolves_correct_type(payload: dict, expected_type: type) -> None:
    op = _OPERATION_ADAPTER.validate_python(payload)
    assert isinstance(op, expected_type)
    assert op.op == payload["op"]


def test_operation_discriminator_rejects_unknown_op() -> None:
    with pytest.raises(ValidationError):
        _OPERATION_ADAPTER.validate_python({"op": "not_a_real_op"})


# --- validate_document -----------------------------------------------------------------------


def test_validate_document_happy_path_all_steps_valid(example_document_json: dict, catalog) -> None:
    doc = AutomationDocument.model_validate(example_document_json)
    new_doc, issues = validate_document(doc, catalog)
    errors = [i for i in issues if i.level == "error"]
    assert errors == []
    assert all(step.valid for step in new_doc.steps)


def test_validate_document_unknown_action_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Unknown",
                settings=ActionSettings(integration="gmail", action="does_not_exist"),
            )
        ],
    )
    new_doc, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert len(errors) == 1
    assert "unknown action" in errors[0].message
    assert new_doc.steps[0].valid is False


def test_validate_document_missing_required_field_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(integration="gmail", action="gmail_search", input={}),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("missing required field" in e.message for e in errors)


def test_validate_document_wrong_literal_type_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={
                        "query": FieldValue(kind="literal", value="dana"),
                        "max_results": FieldValue(kind="literal", value="not a number"),
                    },
                ),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("invalid value for 'max_results'" in e.message for e in errors)


def test_validate_document_unknown_input_field_is_warning() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={
                        "query": FieldValue(kind="literal", value="dana"),
                        "bogus_field": FieldValue(kind="literal", value="x"),
                    },
                ),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    warnings = [i for i in issues if i.level == "warning"]
    assert any("unknown input field" in w.message for w in warnings)


def test_validate_document_ref_to_later_step_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="First",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={
                        "query": FieldValue(kind="ref", value="{{step_bbbbb.output.text}}"),
                    },
                ),
            ),
            ActionStep(
                id="step_bbbbb",
                name="Second",
                settings=ActionSettings(integration="slack", action="slack_send_message"),
            ),
        ],
    )
    new_doc, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("has not run yet" in e.message for e in errors)
    assert new_doc.steps[0].valid is False


def test_validate_document_self_ref_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="First",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={"query": FieldValue(kind="ref", value="{{step_aaaaa.output.text}}")},
                ),
            ),
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("has not run yet" in e.message for e in errors)


def test_validate_document_ref_to_trigger_is_ok() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            AiStep(
                id="step_aaaaa",
                name="Summarize",
                settings=AiStepSettings(instructions="Today is {{trigger.date}}."),
            ),
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    assert issues == []


def test_validate_document_not_connected_integration_is_warning() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={"query": FieldValue(kind="literal", value="dana")},
                ),
            )
        ],
    )
    catalog = StubCatalog(connected=set())
    new_doc, issues = validate_document(doc, catalog)
    warnings = [i for i in issues if i.level == "warning"]
    assert any("not connected" in w.message for w in warnings)
    # a warning alone should not invalidate the step
    assert new_doc.steps[0].valid is True


def test_validate_document_ai_step_json_output_requires_object_schema() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            AiStep(
                id="step_aaaaa",
                name="Summarize",
                settings=AiStepSettings(
                    instructions="Summarize.",
                    output=AiOutput(mode="json", schema_={"type": "array"}),
                ),
            ),
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("output schema" in e.message for e in errors)


def test_validate_document_filter_ref_to_later_step_is_error() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            FilterStep(
                id="step_aaaaa",
                name="Only if",
                settings=FilterSettings(
                    mode="rules",
                    rules=Rules(
                        conditions=[
                            Condition(
                                left=FieldValue(
                                    kind="ref", value="{{step_bbbbb.output.count}}"
                                ),
                                op="gt",
                                right=FieldValue(kind="literal", value=0),
                            )
                        ]
                    ),
                ),
            ),
            ActionStep(
                id="step_bbbbb",
                name="Second",
                settings=ActionSettings(integration="slack", action="slack_send_message"),
            ),
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("has not run yet" in e.message for e in errors)


def test_validate_document_ref_inside_literal_string_is_checked() -> None:
    """A `kind: literal` string can still embed a `{{...}}` template; those refs must be
    checked the same way as an explicit `kind: ref` field."""
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={
                        "query": FieldValue(
                            kind="literal", value="Find mail like {{step_ghost.output}}"
                        )
                    },
                ),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("unknown step" in e.message for e in errors)


def test_validate_document_ref_inside_ai_field_value_is_checked() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Search",
                settings=ActionSettings(
                    integration="gmail",
                    action="gmail_search",
                    input={
                        "query": FieldValue(
                            kind="ai", value="Use {{step_bbbbb.output}} to find the sender"
                        )
                    },
                ),
            ),
            ActionStep(
                id="step_bbbbb",
                name="Second",
                settings=ActionSettings(integration="slack", action="slack_send_message"),
            ),
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("has not run yet" in e.message for e in errors)


def test_validate_document_filter_ai_instruction_ref_is_checked() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            FilterStep(
                id="step_aaaaa",
                name="Only if",
                settings=FilterSettings(
                    mode="ai", instruction="Only continue if {{step_ghost.output}} is urgent"
                ),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("unknown step" in e.message for e in errors)


def test_validate_document_filter_condition_literal_ref_is_checked() -> None:
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            FilterStep(
                id="step_aaaaa",
                name="Only if",
                settings=FilterSettings(
                    mode="rules",
                    rules=Rules(
                        conditions=[
                            Condition(
                                left=FieldValue(
                                    kind="literal", value="{{step_ghost.output}} text"
                                ),
                                op="is_not_empty",
                            )
                        ]
                    ),
                ),
            )
        ],
    )
    _, issues = validate_document(doc, StubCatalog())
    errors = [i for i in issues if i.level == "error"]
    assert any("unknown step" in e.message for e in errors)


def test_validate_document_schema_error_reported_as_issue_not_raised() -> None:
    bad_meta = ActionMeta(
        name="broken_action",
        integration="gmail",
        label="Broken",
        description="Has an invalid JSON schema.",
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "not-a-real-json-schema-type"}},
            "required": [],
        },
    )
    catalog = StubCatalog(actions={"broken_action": bad_meta})
    doc = AutomationDocument(
        name="d",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ManualTrigger(),
        steps=[
            ActionStep(
                id="step_aaaaa",
                name="Broken",
                settings=ActionSettings(
                    integration="gmail",
                    action="broken_action",
                    input={"count": FieldValue(kind="literal", value=1)},
                ),
            )
        ],
    )
    new_doc, issues = validate_document(doc, catalog)  # must not raise
    errors = [i for i in issues if i.level == "error"]
    assert any("invalid input schema" in e.message for e in errors)
    assert new_doc.steps[0].valid is False


def test_validate_document_invalid_cron_surfaces_as_error() -> None:
    doc = AutomationDocument.model_construct(
        name="d",
        description="",
        model=ModelRef(provider="openai", model="gpt-4o-mini"),
        trigger=ScheduleTrigger.model_construct(
            type="schedule",
            settings=ScheduleSettings.model_construct(
                mode="cron", cron="not a cron", every_minutes=None, timezone=None
            ),
        ),
        steps=[],
    )
    _, issues = validate_document(doc, StubCatalog())
    assert any(i.path == "trigger.settings.cron" for i in issues)


# --- diff_summary ------------------------------------------------------------------------


def test_diff_summary_added_action_step() -> None:
    old = _basic_doc()
    new_step = ActionStep(
        id="step_ccccc",
        name="Third",
        settings=ActionSettings(integration="gmail", action="gmail_search"),
    )
    new = apply_operations(old, [AddStep(step=new_step)])
    lines = diff_summary(old, new)
    assert "Added step 'Third' (gmail · gmail_search)" in lines


def test_diff_summary_removed_step() -> None:
    old = _basic_doc()
    new = apply_operations(old, [RemoveStep(step_id="step_bbbbb")])
    lines = diff_summary(old, new)
    assert "Removed step 'Second'" in lines


def test_diff_summary_renamed_automation() -> None:
    old = _basic_doc()
    new = apply_operations(old, [SetMeta(name="New Name")])
    lines = diff_summary(old, new)
    assert "Renamed 'Basic' to 'New Name'" in lines


def test_diff_summary_changed_trigger() -> None:
    old = _basic_doc()
    new = apply_operations(
        old,
        [
            SetTrigger(
                trigger=ScheduleTrigger(
                    settings=ScheduleSettings(mode="cron", cron="0 8 * * 1-5")
                )
            )
        ],
    )
    lines = diff_summary(old, new)
    assert "Changed trigger to weekdays at 08:00" in lines


def test_diff_summary_renamed_step_only() -> None:
    old = _basic_doc()
    new = apply_operations(old, [UpdateStep(step_id="step_aaaaa", patch={"name": "Renamed"})])
    lines = diff_summary(old, new)
    assert "Renamed step 'First' to 'Renamed'" in lines


def test_diff_summary_updated_step_other_change() -> None:
    old = _basic_doc()
    new = apply_operations(
        old, [UpdateStep(step_id="step_aaaaa", patch={"timeout_seconds": 60})]
    )
    lines = diff_summary(old, new)
    assert "Updated step 'First'" in lines


def test_diff_summary_no_changes_is_empty() -> None:
    old = _basic_doc()
    new = apply_operations(old, [])
    assert diff_summary(old, new) == []


def test_describe_trigger() -> None:
    assert describe_trigger(ManualTrigger()) == "manual trigger"
    assert (
        describe_trigger(
            ScheduleTrigger(settings=ScheduleSettings(mode="interval", every_minutes=5))
        )
        == "every 5 minutes"
    )
    assert (
        describe_trigger(
            ScheduleTrigger(settings=ScheduleSettings(mode="cron", cron="0 8 * * 1-5"))
        )
        == "weekdays at 08:00"
    )
    assert (
        describe_trigger(ScheduleTrigger(settings=ScheduleSettings(mode="cron", cron="0 9 * * *")))
        == "daily at 09:00"
    )
