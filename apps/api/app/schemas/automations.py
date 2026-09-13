"""Request/response shapes for the `/automations` API.

Everything here is an `APISchema`, so JSON is camelCase and timestamps are epoch
milliseconds (`int`) — same convention the rest of the API already uses.

Note the deliberate casing split: the *envelope* is camelCase, but the automation
`document` these payloads carry is an opaque `dict` passed through verbatim in the
document language's own snake_case (see `app.schemas.documents`). It is typed as `dict`
rather than `AutomationDocument` on purpose: a draft is allowed to be saved while
invalid, so the API must be able to return a document that would not re-validate, and
`issues` is what tells the client what's wrong with it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import APISchema
from app.schemas.documents import Operation, ValidationIssue

RunTrigger = Literal["manual", "schedule", "test"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunStepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]
VersionAuthor = Literal["user", "assistant", "json", "migration", "restore"]


class LastRunPayload(APISchema):
    """Denormalized pointer to the automation's most recent run, for list rows."""

    status: str
    ended_at: int | None = None


# --- automations -------------------------------------------------------------------------


class AutomationSummary(APISchema):
    id: str
    name: str
    enabled: bool
    trigger_summary: str
    next_run_at: int | None = None
    last_run: LastRunPayload | None = None
    valid: bool
    updated_at: int


class AutomationDetail(APISchema):
    id: str
    name: str
    enabled: bool
    document: dict[str, Any]
    version_number: int
    issues: list[ValidationIssue] = Field(default_factory=list)
    next_run_at: int | None = None
    assistant_messages: list[dict[str, Any]] = Field(default_factory=list)
    last_run: LastRunPayload | None = None
    created_at: int
    updated_at: int


class CreateAutomationRequest(APISchema):
    """Both fields optional: an empty body creates a blank draft named "Untitled
    automation" with the workspace's default model, a manual trigger and no steps.

    When both are given, `document.name` wins — the document is the source of truth for
    an automation's name everywhere else, so `name` only seeds a draft that doesn't
    carry one of its own.
    """

    name: str | None = None
    document: dict[str, Any] | None = None


class PatchAutomationRequest(APISchema):
    name: str | None = None
    enabled: bool | None = None


# --- editing -----------------------------------------------------------------------------


class OperationsRequest(APISchema):
    operations: list[Operation] = Field(default_factory=list)


class OperationsResponse(APISchema):
    """Returned by every endpoint that writes a document (operations, PUT, restore)."""

    document: dict[str, Any]
    issues: list[ValidationIssue] = Field(default_factory=list)
    version_number: int
    summary: list[str] = Field(default_factory=list)


class ReplaceDocumentRequest(APISchema):
    """Whole-document replace (`PUT /automations/{id}`)."""

    document: dict[str, Any]


class ValidateRequest(APISchema):
    document: dict[str, Any]


class ValidateResponse(APISchema):
    document: dict[str, Any]
    issues: list[ValidationIssue] = Field(default_factory=list)


# --- assistant ---------------------------------------------------------------------------


class AssistantRequest(APISchema):
    message: str = Field(min_length=1, max_length=4000)


class AssistantResponse(APISchema):
    """One assistant turn.

    Carries the same `document`/`issues`/`versionNumber` triple as `OperationsResponse`
    (the turn may have edited the document, and the client re-renders from it either
    way), plus what is specific to a conversation: what to say, what was applied, the
    test run it started, the whole transcript, and `error` — set when the assistant's
    operations were rejected and *nothing* was applied, which is a message to show, not
    a failed request.
    """

    message: str
    summary: list[str] = Field(default_factory=list)
    operations_applied: int = 0
    run_id: str | None = None
    document: dict[str, Any]
    issues: list[ValidationIssue] = Field(default_factory=list)
    version_number: int
    assistant_messages: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


# --- versions ----------------------------------------------------------------------------


class VersionSummary(APISchema):
    number: int
    created_by: VersionAuthor
    created_at: int


class VersionDetail(VersionSummary):
    document: dict[str, Any]


# --- runs --------------------------------------------------------------------------------


class RunSummary(APISchema):
    id: str
    automation_id: str
    version_number: int | None = None
    trigger: RunTrigger
    status: RunStatus
    stopped_by_step_id: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    started_at: int | None = None
    ended_at: int | None = None
    duration_ms: int | None = None
    created_at: int


class RunStepPayload(APISchema):
    id: str
    step_id: str
    index: int
    name: str
    type: str
    status: RunStepStatus
    attempt: int = 0
    resolved_input: dict[str, Any] | None = None
    output: Any | None = None
    error: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    started_at: int | None = None
    ended_at: int | None = None
    duration_ms: int | None = None


class RunDetail(RunSummary):
    steps: list[RunStepPayload] = Field(default_factory=list)


class StartRunRequest(APISchema):
    """`schedule` is not accepted here — only the scheduler creates schedule runs."""

    trigger: Literal["manual", "test"] = "manual"


class StartRunResponse(APISchema):
    run_id: str


class CancelRunResponse(APISchema):
    status: RunStatus
