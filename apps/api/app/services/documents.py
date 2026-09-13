"""Pure, DB-free operations on `AutomationDocument`: applying edit operations,
validating against an action catalog, and summarizing the diff between two versions.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Protocol

import jsonschema
from croniter import croniter
from pydantic import TypeAdapter

from app.schemas.documents import (
    ActionStep,
    AddStep,
    AiStep,
    AutomationDocument,
    FilterStep,
    ManualTrigger,
    MoveStep,
    Operation,
    RemoveStep,
    ScheduleTrigger,
    SetMeta,
    SetTrigger,
    Step,
    Trigger,
    UpdateStep,
    ValidationIssue,
)
from app.services.refs import parse_refs

_STEP_ID_ALPHABET = string.digits + string.ascii_lowercase
_STEP_ADAPTER: TypeAdapter[Step] = TypeAdapter(Step)


def new_step_id() -> str:
    """Generate a fresh step id: `step_` + 6 random base36 characters."""
    suffix = "".join(random.choices(_STEP_ID_ALPHABET, k=6))
    return f"step_{suffix}"


def dump_document(doc: AutomationDocument) -> dict:
    """The one canonical way to serialize a document to a plain dict.

    Always `model_dump(by_alias=True, exclude_none=True)` — see the module docstring of
    `app.schemas.documents` for why `exclude_none` matters for a faithful round trip.
    """
    return doc.model_dump(by_alias=True, exclude_none=True)


# --- applying operations -----------------------------------------------------------------


def _find_index(steps: list[Step], step_id: str) -> int:
    for i, step in enumerate(steps):
        if step.id == step_id:
            return i
    raise ValueError(f"unknown step id: {step_id!r}")


def apply_operations(doc: AutomationDocument, ops: list[Operation]) -> AutomationDocument:
    """Apply a list of `Operation`s to `doc`, returning a *new* `AutomationDocument`.

    Raises `ValueError` for unknown step ids, duplicate step ids on add, or out-of-range
    indexes. `doc` itself is never mutated.
    """
    steps: list[Step] = list(doc.steps)
    trigger: Trigger = doc.trigger
    name = doc.name
    description = doc.description
    model = doc.model

    for op in ops:
        if isinstance(op, AddStep):
            if any(s.id == op.step.id for s in steps):
                raise ValueError(f"step id already exists: {op.step.id!r}")
            if op.index is None:
                steps = [*steps, op.step]
            else:
                if not (0 <= op.index <= len(steps)):
                    raise ValueError(f"add_step index out of range: {op.index}")
                steps = [*steps[: op.index], op.step, *steps[op.index :]]

        elif isinstance(op, UpdateStep):
            idx = _find_index(steps, op.step_id)
            current = steps[idx]
            data = current.model_dump(by_alias=True)
            data.update(op.patch)
            new_step = _STEP_ADAPTER.validate_python(data)
            steps = [*steps[:idx], new_step, *steps[idx + 1 :]]

        elif isinstance(op, RemoveStep):
            idx = _find_index(steps, op.step_id)
            steps = [*steps[:idx], *steps[idx + 1 :]]

        elif isinstance(op, MoveStep):
            idx = _find_index(steps, op.step_id)
            step = steps[idx]
            remaining = [*steps[:idx], *steps[idx + 1 :]]
            if not (0 <= op.index <= len(remaining)):
                raise ValueError(f"move_step index out of range: {op.index}")
            steps = [*remaining[: op.index], step, *remaining[op.index :]]

        elif isinstance(op, SetTrigger):
            trigger = op.trigger

        elif isinstance(op, SetMeta):
            if op.name is not None:
                name = op.name
            if op.description is not None:
                description = op.description
            if op.model is not None:
                model = op.model

        else:  # pragma: no cover - discriminated union should make this unreachable
            raise ValueError(f"unknown operation: {op!r}")

    return AutomationDocument(
        name=name, description=description, model=model, trigger=trigger, steps=steps
    )


# --- validation --------------------------------------------------------------------------


@dataclass
class ActionMeta:
    name: str
    integration: str
    label: str
    description: str
    input_schema: dict


class ActionCatalog(Protocol):
    def find_action(self, name: str) -> ActionMeta | None: ...

    def is_connected(self, integration: str) -> bool: ...


def _validate_refs_in_text(
    text: str,
    *,
    current_idx: int,
    current_step_id: str,
    issue_path: str,
    step_index: dict[str, int],
    issues: list[ValidationIssue],
    step_error_flags: dict[str, bool],
) -> None:
    for path in parse_refs(text):
        root = path.split(".", 1)[0].split("[", 1)[0]
        if root == "trigger":
            continue
        if root not in step_index:
            issues.append(
                ValidationIssue(
                    path=issue_path,
                    message=f"reference to unknown step: {root!r}",
                    level="error",
                )
            )
            step_error_flags[current_step_id] = True
        elif step_index[root] >= current_idx:
            issues.append(
                ValidationIssue(
                    path=issue_path,
                    message=f"reference to step that has not run yet (or itself): {root!r}",
                    level="error",
                )
            )
            step_error_flags[current_step_id] = True


def validate_document(
    doc: AutomationDocument, catalog: ActionCatalog
) -> tuple[AutomationDocument, list[ValidationIssue]]:
    """Validate `doc` against `catalog`.

    Returns `(new_doc, issues)` where `new_doc` is a copy of `doc` with each step's
    `valid` flag set to whether that step has zero error-level issues.
    """
    issues: list[ValidationIssue] = []
    step_index = {s.id: i for i, s in enumerate(doc.steps)}
    step_error_flags: dict[str, bool] = dict.fromkeys(step_index, False)

    if isinstance(doc.trigger, ScheduleTrigger):
        settings = doc.trigger.settings
        if settings.mode == "cron" and settings.cron and not croniter.is_valid(settings.cron):
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

    for idx, step in enumerate(doc.steps):
        base_path = f"steps[{idx}]"

        if isinstance(step, ActionStep):
            settings = step.settings
            meta = catalog.find_action(settings.action)
            if meta is None or meta.integration != settings.integration:
                issues.append(
                    ValidationIssue(
                        path=f"{base_path}.settings.action",
                        message=f"unknown action: {settings.integration}.{settings.action}",
                        level="error",
                    )
                )
                step_error_flags[step.id] = True
            else:
                if not catalog.is_connected(settings.integration):
                    issues.append(
                        ValidationIssue(
                            path=f"{base_path}.settings.integration",
                            message=f"integration not connected: {settings.integration}",
                            level="warning",
                        )
                    )

                schema = meta.input_schema or {}
                required = schema.get("required", [])
                properties = schema.get("properties", {})

                for field_name in required:
                    if field_name not in settings.input:
                        issues.append(
                            ValidationIssue(
                                path=f"{base_path}.settings.input.{field_name}",
                                message=f"missing required field: {field_name!r}",
                                level="error",
                            )
                        )
                        step_error_flags[step.id] = True

                for field_name, fv in settings.input.items():
                    field_path = f"{base_path}.settings.input.{field_name}"
                    if field_name not in properties:
                        issues.append(
                            ValidationIssue(
                                path=field_path,
                                message=f"unknown input field: {field_name!r}",
                                level="warning",
                            )
                        )
                        continue

                    if fv.kind == "literal":
                        try:
                            jsonschema.validate(fv.value, properties[field_name])
                        except jsonschema.SchemaError as exc:
                            issues.append(
                                ValidationIssue(
                                    path=field_path,
                                    message=(
                                        f"invalid input schema for field {field_name!r}: "
                                        f"{exc.message}"
                                    ),
                                    level="error",
                                )
                            )
                            step_error_flags[step.id] = True
                        except jsonschema.ValidationError as exc:
                            issues.append(
                                ValidationIssue(
                                    path=field_path,
                                    message=f"invalid value for {field_name!r}: {exc.message}",
                                    level="error",
                                )
                            )
                            step_error_flags[step.id] = True
                        if isinstance(fv.value, str):
                            _validate_refs_in_text(
                                fv.value,
                                current_idx=idx,
                                current_step_id=step.id,
                                issue_path=field_path,
                                step_index=step_index,
                                issues=issues,
                                step_error_flags=step_error_flags,
                            )
                    elif fv.kind in ("ref", "ai"):
                        _validate_refs_in_text(
                            fv.value,
                            current_idx=idx,
                            current_step_id=step.id,
                            issue_path=field_path,
                            step_index=step_index,
                            issues=issues,
                            step_error_flags=step_error_flags,
                        )

        elif isinstance(step, AiStep):
            settings = step.settings
            if settings.output.mode == "json":
                out_schema = settings.output.schema_
                if not isinstance(out_schema, dict) or out_schema.get("type") != "object":
                    issues.append(
                        ValidationIssue(
                            path=f"{base_path}.settings.output.schema",
                            message=(
                                "AI output schema must be a JSON schema object of type "
                                "'object'"
                            ),
                            level="error",
                        )
                    )
                    step_error_flags[step.id] = True

            _validate_refs_in_text(
                settings.instructions,
                current_idx=idx,
                current_step_id=step.id,
                issue_path=f"{base_path}.settings.instructions",
                step_index=step_index,
                issues=issues,
                step_error_flags=step_error_flags,
            )

        elif isinstance(step, FilterStep):
            settings = step.settings
            if settings.mode == "rules" and settings.rules is not None:
                for cidx, cond in enumerate(settings.rules.conditions):
                    for side_name, side in (("left", cond.left), ("right", cond.right)):
                        if side is None:
                            continue
                        text = side.value
                        should_check = (side.kind == "literal" and isinstance(text, str)) or (
                            side.kind in ("ref", "ai")
                        )
                        if should_check:
                            _validate_refs_in_text(
                                text,
                                current_idx=idx,
                                current_step_id=step.id,
                                issue_path=(
                                    f"{base_path}.settings.rules.conditions[{cidx}].{side_name}"
                                ),
                                step_index=step_index,
                                issues=issues,
                                step_error_flags=step_error_flags,
                            )
            elif settings.mode == "ai" and settings.instruction:
                _validate_refs_in_text(
                    settings.instruction,
                    current_idx=idx,
                    current_step_id=step.id,
                    issue_path=f"{base_path}.settings.instruction",
                    step_index=step_index,
                    issues=issues,
                    step_error_flags=step_error_flags,
                )

    new_steps = [
        step.model_copy(update={"valid": not step_error_flags[step.id]}) for step in doc.steps
    ]
    new_doc = doc.model_copy(update={"steps": new_steps})
    return new_doc, issues


# --- diffing -----------------------------------------------------------------------------

_DOW_LABELS = "weekdays"


def describe_trigger(trigger: Trigger) -> str:
    """A short, lowercase, human phrase describing a trigger (for use mid-sentence)."""
    if isinstance(trigger, ManualTrigger):
        return "manual trigger"

    settings = trigger.settings
    if settings.mode == "interval":
        n = settings.every_minutes
        unit = "minute" if n == 1 else "minutes"
        return f"every {n} {unit}"

    cron = settings.cron or ""
    parts = cron.split()
    if len(parts) != 5:
        return f"cron schedule '{cron}'"
    minute, hour, dom, month, dow = parts

    time_part = None
    if minute.isdigit() and hour.isdigit():
        time_part = f"{int(hour):02d}:{int(minute):02d}"

    if time_part and dom == "*" and month == "*" and dow == "1-5":
        return f"{_DOW_LABELS} at {time_part}"
    if time_part and dom == "*" and month == "*" and dow == "*":
        return f"daily at {time_part}"
    return f"cron schedule '{cron}'"


def diff_summary(old: AutomationDocument, new: AutomationDocument) -> list[str]:
    """Human-readable sentences summarizing what changed between `old` and `new`."""
    lines: list[str] = []

    if old.name != new.name:
        lines.append(f"Renamed '{old.name}' to '{new.name}'")

    if old.trigger != new.trigger:
        lines.append(f"Changed trigger to {describe_trigger(new.trigger)}")

    old_by_id = {s.id: s for s in old.steps}
    new_by_id = {s.id: s for s in new.steps}

    for step in new.steps:
        if step.id in old_by_id:
            continue
        if isinstance(step, ActionStep):
            lines.append(
                f"Added step '{step.name}' ({step.settings.integration} · {step.settings.action})"
            )
        else:
            lines.append(f"Added step '{step.name}'")

    for step in old.steps:
        if step.id not in new_by_id:
            lines.append(f"Removed step '{step.name}'")

    for step_id, old_step in old_by_id.items():
        new_step = new_by_id.get(step_id)
        if new_step is None or old_step == new_step:
            continue
        renamed_only = (
            old_step.name != new_step.name
            and old_step.model_copy(update={"name": new_step.name}) == new_step
        )
        if renamed_only:
            lines.append(f"Renamed step '{old_step.name}' to '{new_step.name}'")
        else:
            lines.append(f"Updated step '{new_step.name}'")

    return lines
