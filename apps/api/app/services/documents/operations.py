"""Applying `Operation`s to an `AutomationDocument` — pure and side-effect free."""

from __future__ import annotations

import secrets
import string
from typing import Any

from pydantic import TypeAdapter

from app.schemas.documents import (
    AddStep,
    AutomationDocument,
    MoveStep,
    Operation,
    RemoveStep,
    SetMeta,
    SetTrigger,
    Step,
    Trigger,
    UpdateStep,
)

_STEP_ID_ALPHABET = string.digits + string.ascii_lowercase
_STEP_ADAPTER: TypeAdapter[Step] = TypeAdapter(Step)


def new_step_id() -> str:
    """Generate a fresh step id: `step_` + 6 random base36 characters.

    Uses `secrets` rather than `random`: step ids aren't a security boundary, but
    there's no reason to reach for the weaker PRNG when the stronger one is free.
    """
    suffix = "".join(secrets.choice(_STEP_ID_ALPHABET) for _ in range(6))
    return f"step_{suffix}"


def dump_document(doc: AutomationDocument) -> dict[str, Any]:
    """The one canonical way to serialize a document to a plain dict.

    Always `model_dump(by_alias=True, exclude_none=True)` — see the module docstring of
    `app.schemas.documents` for why `exclude_none` matters for a faithful round trip.
    """
    return doc.model_dump(by_alias=True, exclude_none=True)


def _find_index(steps: list[Step], step_id: str) -> int:
    for i, step in enumerate(steps):
        if step.id == step_id:
            return i
    raise ValueError(f"unknown step id: {step_id!r}")


def _merge_update_step_patch(current: Step, patch: dict[str, Any]) -> dict[str, Any]:
    """Build the dict to re-validate a step from, per `UpdateStep`'s documented
    semantics: shallow-merge onto the step's top-level fields, except `settings`,
    which is merged one level deep into the existing settings dict. `id` is rejected.
    """
    if "id" in patch:
        raise ValueError("update_step patch must not include 'id'")

    data = current.model_dump(by_alias=True)
    if "settings" in patch:
        patch_settings = patch["settings"]
        existing_settings = data.get("settings")
        if isinstance(patch_settings, dict) and isinstance(existing_settings, dict):
            patch = {**patch, "settings": {**existing_settings, **patch_settings}}
    data.update(patch)
    return data


def apply_operations(doc: AutomationDocument, ops: list[Operation]) -> AutomationDocument:
    """Apply a list of `Operation`s to `doc`, returning a *new* `AutomationDocument`.

    Raises `ValueError` for unknown step ids, duplicate step ids on add, out-of-range
    indexes, or an `update_step` patch that includes `id`. `doc` itself is never
    mutated — documents are frozen (`app.schemas.documents.DocSchema`), so a caller
    holding a reference to `doc` is guaranteed it hasn't changed underneath it.
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
            data = _merge_update_step_patch(steps[idx], op.patch)
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
