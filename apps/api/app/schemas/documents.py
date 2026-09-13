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
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from zoneinfo import available_timezones

from croniter import croniter
from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.base import APISchema

REF_PATTERN = r"^\{\{\s*[A-Za-z0-9_]+(\.[A-Za-z0-9_]+|\[\d+\])*\s*\}\}$"
_REF_RE = re.compile(REF_PATTERN)


class DocSchema(APISchema):
    """Base for automation-document models: snake_case field names, snake_case JSON."""

    model_config = ConfigDict(alias_generator=None, populate_by_name=True, from_attributes=True)


# --- field values (literal / ref / ai) --------------------------------------------------


class FieldValue(DocSchema):
    kind: Literal["literal", "ref", "ai"]
    value: Any = None

    @model_validator(mode="after")
    def _check_value(self) -> FieldValue:
        if self.kind == "ref":
            if not isinstance(self.value, str) or not _REF_RE.match(self.value):
                raise ValueError(
                    f"ref value must look like '{{{{step_x.output}}}}', got {self.value!r}"
                )
        elif self.kind == "ai":
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("ai value must be a non-empty string")
        return self


class RetryPolicy(DocSchema):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_seconds: float = Field(default=10, ge=0, le=300)


# --- action steps ------------------------------------------------------------------------


class ActionSettings(DocSchema):
    integration: str
    action: str
    input: dict[str, FieldValue] = Field(default_factory=dict)


# --- ai steps ------------------------------------------------------------------------------


class AiOutput(DocSchema):
    mode: Literal["text", "json"] = "text"
    schema_: dict | None = Field(default=None, alias="schema")


class AiStepSettings(DocSchema):
    instructions: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    output: AiOutput = Field(default_factory=AiOutput)


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


class Condition(DocSchema):
    left: FieldValue
    op: ConditionOp
    right: FieldValue | None = None


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
    timeout_seconds: int | None = None
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
        if v is not None and v not in available_timezones():
            raise ValueError(f"unknown timezone: {v!r}")
        return v

    @model_validator(mode="after")
    def _check_mode_fields(self) -> ScheduleSettings:
        if self.mode == "cron":
            if not self.cron:
                raise ValueError("cron mode requires a non-empty 'cron' expression")
            if not croniter.is_valid(self.cron):
                raise ValueError(f"invalid cron expression: {self.cron!r}")
        elif self.mode == "interval" and self.every_minutes is None:
            raise ValueError("interval mode requires 'every_minutes'")
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
        ids = [s.id for s in steps]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate step ids: {dupes}")
        return steps


# --- operations --------------------------------------------------------------------------


class AddStep(DocSchema):
    op: Literal["add_step"] = "add_step"
    step: Step
    index: int | None = None


class UpdateStep(DocSchema):
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
