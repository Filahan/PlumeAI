"""The automation document language: Pydantic v2 schemas for an automation document
(one trigger + an ordered list of steps), the mutation `Operation`s applied to it, and
`ValidationIssue` used to report problems back to the client.

Canonical casing: **snake_case**, matching the document JSON exactly (e.g.
`backoff_seconds`, `max_results`, `not_contains`, `every_minutes`). This differs from
`app.schemas.base.APISchema`, whose `to_camel` alias generator is meant for per-endpoint
request/response shapes shared with the TypeScript client. The automation document is a
stored/interchange format instead — it is read and written verbatim (DB column, executor
input, operation payloads) — so it keeps one casing everywhere. Models here still inherit
`APISchema` for `populate_by_name` / `from_attributes`, but override the alias generator
so `model_dump(by_alias=True)` and `model_validate` round-trip the document unchanged.

Canonical serialization: always dump a document with
`doc.model_dump(by_alias=True, exclude_none=True)` (or, for JSON text,
`doc.model_dump_json(by_alias=True, exclude_none=True)`) — `exclude_none` drops unset
optional fields (e.g. `retry`, `timeout_seconds`, `every_minutes`) instead of writing
them as explicit `null`s, which is what keeps the round trip byte-for-byte identical to
the document as authored. `app.services.documents.dump_document` wraps this exact call
so every caller uses the same one. One consequence: this normalizes away the difference
between an *absent* optional key and one explicitly set to `null` — loading a document
that has `"retry": null` and dumping it again produces a document with no `retry` key at
all, not a `null` one; the two are treated as identical everywhere in this module.

All models are **frozen** (immutable after construction) — see `DocSchema.model_config`.
`app.services.documents.apply_operations` never mutates a document in place; it builds
new model instances (via `model_copy(update=...)` or fresh construction) and returns
them, so a caller holding a reference to the old document is guaranteed it hasn't
changed out from under it.

The `{{ path }}` reference grammar used by `kind: "ref"` `FieldValue`s lives in the leaf
module `app.schemas.refs` (not here), so both this module and `app.services.refs` can
import it without an import cycle.
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.base import APISchema
from app.schemas.refs import REF_FULLMATCH_RE


class DocSchema(APISchema):
    """Base for automation-document models: snake_case field names, snake_case JSON,
    and frozen (immutable after construction) so documents can be shared/aliased freely.
    """

    model_config = ConfigDict(
        alias_generator=None, populate_by_name=True, from_attributes=True, frozen=True
    )


# --- field values (literal / ref / ai) --------------------------------------------------


class FieldValue(DocSchema):
    kind: Literal["literal", "ref", "ai"]
    value: Any = None

    @model_validator(mode="after")
    def _check_value(self) -> FieldValue:
        if self.kind == "ref":
            if not isinstance(self.value, str) or not REF_FULLMATCH_RE.fullmatch(self.value):
                raise ValueError(
                    f"ref value must look like '{{{{step_x.output}}}}', got {self.value!r}"
                )
        elif self.kind == "ai":
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("ai value must be a non-empty string")
        return self


class RetryPolicy(DocSchema):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_seconds: int = Field(default=10, ge=0, le=300)


# --- action steps ------------------------------------------------------------------------


class ActionSettings(DocSchema):
    integration: str
    action: str
    input: dict[str, FieldValue] = Field(default_factory=dict)


# --- ai steps ------------------------------------------------------------------------------


class AiOutput(DocSchema):
    mode: Literal["text", "json"] = "text"
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class AiStepSettings(DocSchema):
    instructions: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    output: AiOutput = Field(default_factory=AiOutput)

    @field_validator("tools")
    @classmethod
    def _check_tool_names(cls, tools: list[str]) -> list[str]:
        for tool in tools:
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError(f"tool names must be non-empty strings, got {tool!r}")
        return tools


# --- filter steps --------------------------------------------------------------------------

ConditionOp = Literal[
    "eq",
    "neq",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_empty",
    "is_not_empty",
    "is_true",
    "is_false",
]

_UNARY_CONDITION_OPS = frozenset({"is_empty", "is_not_empty", "is_true", "is_false"})


class Condition(DocSchema):
    left: FieldValue
    op: ConditionOp
    right: FieldValue | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Condition:
        if self.left.kind == "ai":
            raise ValueError(
                "condition 'left' cannot use kind 'ai' (AI resolution isn't available "
                "inside filter rules)"
            )
        if self.right is not None and self.right.kind == "ai":
            raise ValueError(
                "condition 'right' cannot use kind 'ai' (AI resolution isn't available "
                "inside filter rules)"
            )
        if self.op in _UNARY_CONDITION_OPS:
            if self.right is not None:
                raise ValueError(f"condition op {self.op!r} does not take a 'right' operand")
        elif self.right is None:
            raise ValueError(f"condition op {self.op!r} requires a 'right' operand")
        return self


class Rules(DocSchema):
    combinator: Literal["and", "or"] = "and"
    conditions: list[Condition] = Field(min_length=1)


class FilterSettings(DocSchema):
    mode: Literal["rules", "ai"]
    rules: Rules | None = None
    instruction: str | None = None

    @model_validator(mode="after")
    def _check_mode_fields(self) -> FilterSettings:
        if self.mode == "rules" and self.rules is None:
            raise ValueError("filter mode 'rules' requires 'rules' to be set")
        if self.mode == "ai" and not self.instruction:
            raise ValueError("filter mode 'ai' requires a non-empty 'instruction'")
        return self


# --- steps -----------------------------------------------------------------------------


class StepBase(DocSchema):
    id: str = Field(pattern=r"^step_[a-z0-9]{5,}$")
    name: str
    retry: RetryPolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    valid: bool = True


class ActionStep(StepBase):
    type: Literal["action"] = "action"
    settings: ActionSettings


class AiStep(StepBase):
    type: Literal["ai"] = "ai"
    settings: AiStepSettings


class FilterStep(StepBase):
    type: Literal["filter"] = "filter"
    settings: FilterSettings


Step = Annotated[Union[ActionStep, AiStep, FilterStep], Field(discriminator="type")]


# --- trigger -----------------------------------------------------------------------------


class ScheduleSettings(DocSchema):
    mode: Literal["cron", "interval"]
    cron: str | None = None
    every_minutes: int | None = Field(default=None, ge=1, le=10080)
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (KeyError, ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _check_mode_fields(self) -> ScheduleSettings:
        if self.mode == "cron":
            if not self.cron:
                raise ValueError("cron mode requires a non-empty 'cron' expression")
            if not croniter.is_valid(self.cron):
                raise ValueError(f"invalid cron expression: {self.cron!r}")
            if self.every_minutes is not None:
                raise ValueError("cron mode must not also set 'every_minutes'")
        elif self.mode == "interval":
            if self.every_minutes is None:
                raise ValueError("interval mode requires 'every_minutes'")
            if self.cron is not None:
                raise ValueError("interval mode must not also set 'cron'")
        return self


class ManualTrigger(DocSchema):
    type: Literal["manual"] = "manual"


class ScheduleTrigger(DocSchema):
    type: Literal["schedule"] = "schedule"
    settings: ScheduleSettings


Trigger = Annotated[Union[ManualTrigger, ScheduleTrigger], Field(discriminator="type")]


class ModelRef(DocSchema):
    provider: Literal["openai", "anthropic"]
    model: str


# --- the document itself ------------------------------------------------------------------


class AutomationDocument(DocSchema):
    name: str
    description: str = ""
    model: ModelRef
    trigger: Trigger
    steps: list[Step] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def _unique_step_ids(cls, steps: list[Step]) -> list[Step]:
        counts = Counter(s.id for s in steps)
        dupes = sorted(step_id for step_id, count in counts.items() if count > 1)
        if dupes:
            raise ValueError(f"duplicate step ids: {dupes}")
        return steps


# --- operations --------------------------------------------------------------------------


class AddStep(DocSchema):
    op: Literal["add_step"] = "add_step"
    step: Step
    index: int | None = None


class UpdateStep(DocSchema):
    """Edit an existing step by shallow-merging `patch` onto its top-level fields
    (`name`, `retry`, `timeout_seconds`, `valid`, ...) — each key in `patch` simply
    overwrites the corresponding field.

    `settings` is the one exception: when `patch` includes a `settings` key, it is
    merged **one level deep** into the step's existing settings dict (so
    `{"settings": {"action": "x"}}` changes only `action`, leaving `integration`/
    `input`/etc. as they were), rather than replacing the whole settings object — a
    caller that wants to fully replace a nested value (e.g. `input`) includes that
    whole key in `patch["settings"]`.

    `patch` must not include `id` — an `update_step` cannot re-identify a step.
    """

    op: Literal["update_step"] = "update_step"
    step_id: str
    patch: dict[str, Any] = Field(default_factory=dict)


class RemoveStep(DocSchema):
    op: Literal["remove_step"] = "remove_step"
    step_id: str


class MoveStep(DocSchema):
    op: Literal["move_step"] = "move_step"
    step_id: str
    index: int


class SetTrigger(DocSchema):
    op: Literal["set_trigger"] = "set_trigger"
    trigger: Trigger


class SetMeta(DocSchema):
    op: Literal["set_meta"] = "set_meta"
    name: str | None = None
    description: str | None = None
    model: ModelRef | None = None


Operation = Annotated[
    Union[AddStep, UpdateStep, RemoveStep, MoveStep, SetTrigger, SetMeta],
    Field(discriminator="op"),
]


# --- validation issues ---------------------------------------------------------------------


class ValidationIssue(DocSchema):
    path: str
    message: str
    level: Literal["error", "warning"]
