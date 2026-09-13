"""Validating an `AutomationDocument` against an action catalog.

`validate_document` must never raise, even on adversarial input: a malformed catalog
schema (bad `$ref`, an unknown JSON-schema `type`, ...) or a hostile document should
turn into `ValidationIssue`s, never an unhandled exception. Every place that calls into
a "trusts its input" library (`jsonschema`, `croniter`) is wrapped accordingly, and the
per-step dispatch has one more `except Exception` around it as a last line of defense.

Beyond "does this field exist and is this literal the right type", the validator also
does a *static shape check* on `kind: "ref"` values: it infers what a referenced path
will yield at run time (from the document and the catalog alone — never from a run) and
flags the one unambiguous mismatch, a reference that certainly resolves to an object or
a list feeding a field declared as a scalar. See `_check_ref_shape` for why everything
short of certain stays silent.
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
from app.services.refs import parse_refs, ref_step_id, ref_tokens


@dataclass
class ActionMeta:
    """The slice of a catalog action this module reads. Structurally a subset of
    `app.tools.base.CatalogAction`, which is what the live `Catalog` actually hands over.

    `output_schema` is optional and frequently absent: an action that returns only free
    text publishes none, and "no declared output" must stay *unknown* here rather than
    being guessed at — see `_step_output_schema`.
    """

    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


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
    steps_by_id: dict[str, Step]
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


# --- static shape inference for `ref` field values ----------------------------------------
#
# A `kind: "ref"` field hands the *resolved value* to the action verbatim (see
# `resolve_action_input`): there is no stringification step on the way, so a reference
# that resolves to `{"text": "..."}` reaches a `"type": "string"` field as a dict and the
# action rejects it — three times, once per retry, and only at run time. Everything below
# exists to catch that statically, from the document and the catalog alone.

# The run-time output shapes `app.services.step_runner` produces for the step types whose
# output isn't author-declared. Kept as JSON schemas so one `_walk_schema` handles every
# source uniformly.
_AI_TEXT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
}
_FILTER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"continue": {"type": "boolean"}, "reason": {"type": "string"}},
}
# `{{trigger.…}}` resolves against the context built by `executor._trigger_context`.
_TRIGGER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "now": {"type": "string"},
        "date": {"type": "string"},
        "timezone": {"type": "string"},
    },
}

_KNOWN_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)

# How to name the shape the reference yields, and what the field wanted instead — in the
# user's words, not JSON Schema's. `_SHAPE_WORDS` doubles as the list of shapes worth
# complaining about: only a container is certainly wrong in a scalar field.
_SHAPE_WORDS = {"object": "an object", "array": "a list"}
_FIELD_NEEDS = {
    "string": "text",
    "number": "a number",
    "integer": "a whole number",
    "boolean": "true or false",
}

# The only condition ops that genuinely cannot cope with a container: `_as_number` raises
# on one. `contains`/`eq`/`is_empty` all have defined behaviour for dicts and lists, so a
# container there is not a mistake worth flagging.
_NUMERIC_CONDITION_OPS = frozenset({"gt", "gte", "lt", "lte"})


@dataclass(frozen=True)
class _RefShape:
    """What a reference path is *known* to yield. Only ever constructed when the type is
    certain; "don't know" is spelled `None` by the functions that build it."""

    type: str
    source: str
    """How to refer to what the reference points at, e.g. "the whole result of 'Summarize'"."""

    suggestion: str | None
    """A concrete `{{...}}` path to use instead, when exactly one is obvious."""


def _schema_type(schema: Any) -> str | None:
    """The single JSON type a subschema certainly declares.

    `None` for anything less than certain: a missing/unknown `type`, or a union
    (`["string", "null"]`), which says the value may or may not be a container.
    """
    if not isinstance(schema, dict):
        return None
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared if declared in _KNOWN_TYPES else None
    if declared is None:
        # A schema that names `properties`/`items` but omits `type` still pins the
        # container kind, and catalog schemas written by hand do this often enough.
        if isinstance(schema.get("properties"), dict):
            return "object"
        if "items" in schema:
            return "array"
    return None


def _walk_schema(schema: Any, tokens: list[str]) -> dict[str, Any] | None:
    """Follow reference-path `tokens` into a JSON schema, returning the subschema they
    land on, or `None` as soon as the schema stops describing where the path goes."""
    current: Any = schema
    for tok in tokens:
        if not isinstance(current, dict):
            return None
        if tok.startswith("["):
            if _schema_type(current) != "array":
                return None
            current = current.get("items")
        else:
            props = current.get("properties")
            if not isinstance(props, dict) or tok not in props:
                return None
            current = props[tok]
    return current if isinstance(current, dict) else None


def _step_output_schema(step: Step, catalog: ActionCatalog) -> dict[str, Any] | None:
    """The JSON schema a step's `output` is known to have, or `None` when unknowable.

    "Unknowable" is a real answer here, not a failure: an action that publishes no
    `output_schema` (most of them return free text) tells us nothing about its shape, and
    inventing one would manufacture false positives.
    """
    if isinstance(step, AiStep):
        if step.settings.output.mode == "json":
            declared = step.settings.output.schema_
            return declared if isinstance(declared, dict) else None
        return _AI_TEXT_OUTPUT_SCHEMA
    if isinstance(step, FilterStep):
        return _FILTER_OUTPUT_SCHEMA
    if isinstance(step, ActionStep):
        try:
            meta = catalog.find_action(step.settings.action)
        except Exception:  # noqa: BLE001 - a catalog that throws just means "unknown"
            return None
        declared = getattr(meta, "output_schema", None)
        return declared if isinstance(declared, dict) else None
    return None  # pragma: no cover - the discriminated union has no fourth member


def _scalar_suggestion(schema: dict[str, Any], path: str) -> str | None:
    """The one obvious scalar path inside `schema`, spelled as a `{{ ref }}`.

    Deliberately narrow: an AI *text* step's output has exactly one `text` string, and a
    one-property object output has exactly one candidate. With two or more properties
    there is no single obvious answer, and picking one for the user would be a guess.
    """
    props = schema.get("properties")
    if not isinstance(props, dict) or len(props) != 1:
        return None
    name, sub = next(iter(props.items()))
    if _schema_type(sub) != "string" or not isinstance(name, str):
        return None
    return f"{{{{{path}.{name}}}}}"


def _infer_ref_shape(path: str, ctx: _ValidationContext) -> _RefShape | None:
    """What `path` will resolve to at run time, or `None` when that isn't certain."""
    try:
        tokens = ref_tokens(path)
    except Exception:  # noqa: BLE001 - an unparseable path is simply unknown here
        return None
    root, rest = tokens[0], tokens[1:]

    if root == "trigger":
        base_schema: dict[str, Any] | None = _TRIGGER_SCHEMA
        source = "the whole trigger context" if not rest else f"'{{{{{path}}}}}'"
    else:
        idx = ctx.step_index.get(root)
        # A dangling or forward reference already has its own, more useful error from
        # `check_refs`; adding a shape complaint on top would only be noise.
        if idx is None or idx >= ctx.idx:
            return None
        step = ctx.steps_by_id[root]
        if not rest or rest[0] != "output":
            return None
        rest = rest[1:]
        base_schema = _step_output_schema(step, ctx.catalog)
        source = f"the whole result of {step.name!r}" if not rest else f"'{{{{{path}}}}}'"

    if base_schema is None:
        return None
    landed = _walk_schema(base_schema, rest)
    shape = _schema_type(landed)
    if landed is None or shape is None:
        return None
    return _RefShape(type=shape, source=source, suggestion=_scalar_suggestion(landed, path))


def _check_ref_shape(
    fv: FieldValue, field_path: str, expected_type: str | None, ctx: _ValidationContext
) -> None:
    """Flag a `ref` that certainly resolves to a container feeding a scalar field.

    Only that one direction is reported, and only at `error` level, because it is the
    only mismatch that is certainly wrong at run time. Every other case stays **silent**
    on purpose — an unknown step, an action with no published `output_schema`, a union
    type, a path the schema doesn't describe, a scalar-into-scalar near miss. A wrong
    error costs the author more than the missing one it would have caught, and a warning
    for every "maybe" would train people to ignore the panel.
    """
    if fv.kind != "ref" or expected_type not in _FIELD_NEEDS:
        return
    paths = parse_refs(fv.value) if isinstance(fv.value, str) else []
    if len(paths) != 1:
        return
    shape = _infer_ref_shape(paths[0], ctx)
    if shape is None or shape.type not in _SHAPE_WORDS:
        return
    message = (
        f"references {shape.source}, which is {_SHAPE_WORDS[shape.type]}; "
        f"this field needs {_FIELD_NEEDS[expected_type]}"
    )
    if shape.suggestion is not None:
        message += f" — use {shape.suggestion}"
    ctx.add_issue(field_path, message, "error")


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

        field_schema = properties.get(field_name) if isinstance(properties, dict) else None
        if fv.kind == "literal":
            _check_literal_against_schema(fv, field_name, field_path, schema, ctx)
        elif fv.kind == "ref":
            _check_ref_shape(fv, field_path, _schema_type(field_schema), ctx)


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
                if side.kind == "ref" and cond.op in _NUMERIC_CONDITION_OPS:
                    # The op is the only type declaration a condition side has, and
                    # only the numeric comparisons pin it down (`_as_number` raises on
                    # a container); `eq`/`contains`/`is_empty` all accept one.
                    _check_ref_shape(side, side_path, "number", ctx)
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
    steps_by_id = {s.id: s for s in doc.steps}
    step_error_flags: dict[str, bool] = dict.fromkeys(step_index, False)

    _validate_trigger(doc, issues)

    for idx, step in enumerate(doc.steps):
        ctx = _ValidationContext(
            idx=idx,
            step=step,
            base_path=f"steps[{idx}]",
            step_index=step_index,
            steps_by_id=steps_by_id,
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
