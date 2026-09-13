"""Validating an `AutomationDocument` against an action catalog.

`validate_document` must never raise, even on adversarial input: a malformed catalog
schema (bad `$ref`, an unknown JSON-schema `type`, ...) or a hostile document should
turn into `ValidationIssue`s, never an unhandled exception. Every place that calls into
a "trusts its input" library (`jsonschema`, `croniter`) is wrapped accordingly, and the
per-step dispatch has one more `except Exception` around it as a last line of defense.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import jsonschema
from croniter import croniter
from jsonschema import Draft202012Validator

from app.schemas.documents import (
    ActionStep,
    AiStep,
    AutomationDocument,
    FieldValue,
    FilterStep,
    ManualTrigger,
    ScheduleTrigger,
    Step,
    ValidationIssue,
)
from app.services.refs import parse_refs, ref_step_id


@dataclass
class ActionMeta:
    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]


class ActionCatalog(Protocol):
    def find_action(self, name: str) -> ActionMeta | None: ...

    def is_connected(self, integration: str) -> bool: ...


@dataclass
class _ValidationContext:
    """Per-step scratch state passed to the step-type validators below, replacing what
    used to be a 7-keyword-argument helper function."""

    idx: int
    step: Step
    base_path: str
    step_index: dict[str, int]
    catalog: ActionCatalog
    issues: list[ValidationIssue]
    step_error_flags: dict[str, bool]

    def add_issue(self, path: str, message: str, level: str) -> None:
        self.issues.append(ValidationIssue(path=path, message=message, level=level))
        if level == "error":
            self.step_error_flags[self.step.id] = True

    def check_refs(self, text: str, path: str) -> None:
        """Every `{{ ref }}` found in `text` must point at a step that exists and runs
        strictly before this one (or at the literal `trigger` root)."""
        for ref_path in parse_refs(text):
            root = ref_step_id(ref_path)
            if root == "trigger":
                continue
            if root not in self.step_index:
                self.add_issue(path, f"reference to unknown step: {root!r}", "error")
            elif self.step_index[root] >= self.idx:
                self.add_issue(
                    path,
                    f"reference to step that has not run yet (or itself): {root!r}",
                    "error",
                )


def _check_literal_against_schema(
    fv: FieldValue,
    field_name: str,
    field_path: str,
    full_schema: dict[str, Any],
    ctx: _ValidationContext,
) -> None:
    if isinstance(fv.value, str) and parse_refs(fv.value):
        # A templated literal (e.g. "Hi {{step_x.output.name}}") is resolved at
        # runtime via string interpolation into a *string* — checking today's literal
        # text against the field's declared JSON type would be meaningless (and often
        # wrong: a templated integer field is still a valid literal). The refs
        # themselves were already checked by the caller regardless of field type.
        return

    properties = full_schema.get("properties", {}) if isinstance(full_schema, dict) else {}
    field_schema = properties.get(field_name, {})
    try:
        validator = Draft202012Validator(full_schema)
        # `.evolve()` swaps in the field-level subschema while keeping the parent
        # validator's resolver/registry, so a `$ref` relative to the full catalog
        # schema still resolves correctly.
        validator.evolve(schema=field_schema).validate(fv.value)
    except jsonschema.exceptions.SchemaError as exc:
        ctx.add_issue(
            field_path,
            f"invalid input schema for field {field_name!r}: {exc.message}",
            "error",
        )
    except jsonschema.exceptions.ValidationError as exc:
        ctx.add_issue(field_path, f"invalid value for {field_name!r}: {exc.message}", "error")
    except Exception as exc:  # noqa: BLE001 - a malformed catalog schema must not raise
        ctx.add_issue(field_path, f"could not validate field {field_name!r}: {exc}", "error")


def _validate_action_step(step: ActionStep, ctx: _ValidationContext) -> None:
    settings = step.settings
    meta = ctx.catalog.find_action(settings.action)
    if meta is None or meta.integration != settings.integration:
        ctx.add_issue(
            f"{ctx.base_path}.settings.action",
            f"unknown action: {settings.integration}.{settings.action}",
            "error",
        )
        return

    if not ctx.catalog.is_connected(settings.integration):
        ctx.add_issue(
            f"{ctx.base_path}.settings.integration",
            f"integration not connected: {settings.integration}",
            "warning",
        )

    schema = meta.input_schema if isinstance(meta.input_schema, dict) else {}
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field_name in required:
        if field_name not in settings.input:
            ctx.add_issue(
                f"{ctx.base_path}.settings.input.{field_name}",
                f"missing required field: {field_name!r}",
                "error",
            )

    for field_name, fv in settings.input.items():
        field_path = f"{ctx.base_path}.settings.input.{field_name}"

        # Refs are checked regardless of whether the field name is known to the
        # catalog schema — a dangling/forward step reference is a bug either way.
        if fv.kind in ("ref", "ai") or (fv.kind == "literal" and isinstance(fv.value, str)):
            ctx.check_refs(fv.value, field_path)

        if field_name not in properties:
            ctx.add_issue(field_path, f"unknown input field: {field_name!r}", "warning")
            continue

        if fv.kind == "literal":
            _check_literal_against_schema(fv, field_name, field_path, schema, ctx)


def _validate_ai_step(step: AiStep, ctx: _ValidationContext) -> None:
    settings = step.settings

    if settings.output.mode == "json":
        out_schema = settings.output.schema_
        if not isinstance(out_schema, dict) or out_schema.get("type") != "object":
            ctx.add_issue(
                f"{ctx.base_path}.settings.output.schema",
                "AI output schema must be a JSON schema object of type 'object'",
                "error",
            )

    ctx.check_refs(settings.instructions, f"{ctx.base_path}.settings.instructions")

    for tool_idx, tool_name in enumerate(settings.tools):
        if ctx.catalog.find_action(tool_name) is None:
            ctx.add_issue(
                f"{ctx.base_path}.settings.tools[{tool_idx}]",
                f"unknown tool: {tool_name!r}",
                "warning",
            )


def _validate_filter_step(step: FilterStep, ctx: _ValidationContext) -> None:
    settings = step.settings
    if settings.mode == "rules" and settings.rules is not None:
        for cidx, cond in enumerate(settings.rules.conditions):
            for side_name, side in (("left", cond.left), ("right", cond.right)):
                if side is None:
                    continue
                side_path = f"{ctx.base_path}.settings.rules.conditions[{cidx}].{side_name}"
                if side.kind == "ai":
                    # The schema already rejects `kind: "ai"` inside a `Condition` for
                    # normally-constructed documents (see `Condition._check_shape`);
                    # this is defense in depth for a document built via
                    # `model_construct` (e.g. a legacy/hand-built row).
                    ctx.add_issue(
                        side_path,
                        "AI-resolved values are not supported inside filter conditions",
                        "error",
                    )
                    continue
                if side.kind == "ref" or (side.kind == "literal" and isinstance(side.value, str)):
                    ctx.check_refs(side.value, side_path)
    elif settings.mode == "ai" and settings.instruction:
        ctx.check_refs(settings.instruction, f"{ctx.base_path}.settings.instruction")


_STEP_VALIDATORS: dict[type, Callable[[Any, _ValidationContext], None]] = {
    ActionStep: _validate_action_step,
    AiStep: _validate_ai_step,
    FilterStep: _validate_filter_step,
}


def _validate_trigger(doc: AutomationDocument, issues: list[ValidationIssue]) -> None:
    if isinstance(doc.trigger, ScheduleTrigger):
        settings = doc.trigger.settings
        try:
            is_valid_cron = (
                settings.mode != "cron" or not settings.cron or croniter.is_valid(settings.cron)
            )
        except Exception:  # noqa: BLE001 - croniter is a third-party parser
            is_valid_cron = False
        if not is_valid_cron:
            issues.append(
                ValidationIssue(
                    path="trigger.settings.cron",
                    message=f"invalid cron expression: {settings.cron!r}",
                    level="error",
                )
            )
    elif not isinstance(doc.trigger, ManualTrigger):  # pragma: no cover - defensive
        issues.append(
            ValidationIssue(path="trigger.type", message="unknown trigger type", level="error")
        )


def validate_document(
    doc: AutomationDocument, catalog: ActionCatalog
) -> tuple[AutomationDocument, list[ValidationIssue]]:
    """Validate `doc` against `catalog`.

    Returns `(new_doc, issues)` where `new_doc` is a copy of `doc` with each step's
    `valid` flag set to whether that step has zero error-level issues. Never raises.
    """
    issues: list[ValidationIssue] = []
    step_index = {s.id: i for i, s in enumerate(doc.steps)}
    step_error_flags: dict[str, bool] = dict.fromkeys(step_index, False)

    _validate_trigger(doc, issues)

    for idx, step in enumerate(doc.steps):
        ctx = _ValidationContext(
            idx=idx,
            step=step,
            base_path=f"steps[{idx}]",
            step_index=step_index,
            catalog=catalog,
            issues=issues,
            step_error_flags=step_error_flags,
        )
        validator = _STEP_VALIDATORS.get(type(step))
        if validator is None:  # pragma: no cover - discriminated union prevents this
            ctx.add_issue(ctx.base_path, f"unknown step type: {type(step).__name__}", "error")
            continue
        try:
            validator(step, ctx)
        except Exception as exc:  # noqa: BLE001 - validate_document must never raise
            ctx.add_issue(ctx.base_path, f"internal error validating step: {exc}", "error")

    new_steps = [
        step.model_copy(update={"valid": not step_error_flags[step.id]}) for step in doc.steps
    ]
    new_doc = doc.model_copy(update={"steps": new_steps})
    return new_doc, issues
