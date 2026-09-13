"""Automation persistence: the draft document, its version history, and the small amount
of denormalized state the list view needs.

Two rules shape everything here:

1. **A draft is always saveable.** Validation issues (unknown action, dangling `{{ref}}`,
   disconnected integration, ...) never block a write — they are returned to the caller
   and recorded in the document as per-step `valid` flags, so the builder can show a
   half-finished automation with red steps instead of refusing the edit. The one
   exception is `created_by="json"` (the raw whole-document PUT), where a payload that
   isn't even a well-formed `AutomationDocument` is a client error, not a draft.

2. **A version is only written when the document actually changed.** `apply_operations`
   on a no-op edit, or a restore of the version that's already current, leaves the
   history alone; `save_document` compares the canonical dump against the current
   version's stored document to decide.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Automation, AutomationVersion
from app.errors import BadRequest, NotFound, ValidationFailure
from app.schemas.documents import (
    AutomationDocument,
    Operation,
    ValidationIssue,
)
from app.services import scheduler
from app.services.catalog import build_catalog
from app.services.documents import (
    apply_operations,
    diff_summary,
    dump_document,
    validate_document,
)
from app.services.settings import get_settings_for_client

log = structlog.get_logger("app.automations")

DEFAULT_NAME = "Untitled automation"

# Who wrote a version: a builder edit, the AI assistant, a raw JSON PUT, the legacy-task
# migration, or restoring an older version.
CreatedBy = str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _issues_from_pydantic(exc: PydanticValidationError) -> list[dict[str, Any]]:
    """Pydantic errors rendered in the same `{path, message, level}` shape as
    `ValidationIssue`, so a client renders PUT failures with the same code path it uses
    for catalog validation issues."""
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        path = ".".join(str(p) for p in err.get("loc", ())) or "document"
        out.append({"path": path, "message": err.get("msg", "invalid"), "level": "error"})
    return out


def _coerce_document(raw: Any, *, created_by: CreatedBy) -> AutomationDocument:
    if isinstance(raw, AutomationDocument):
        return raw
    try:
        return AutomationDocument.model_validate(raw)
    except PydanticValidationError as exc:
        issues = _issues_from_pydantic(exc)
        if created_by == "json":
            raise ValidationFailure(
                "Document does not match the automation document schema.",
                extra={"issues": issues},
            ) from exc
        # Anything else handing us an unparseable document is an internal caller bug.
        raise BadRequest(
            "Document does not match the automation document schema.",
            extra={"issues": issues},
        ) from exc


async def _default_document(session: AsyncSession, name: str | None) -> AutomationDocument:
    """A blank draft: the workspace default model, a manual trigger, no steps."""
    settings = await get_settings_for_client(session)
    default_model = settings.default_model
    provider = default_model.provider
    if provider not in {"openai", "anthropic"}:
        # `ModelRef` only knows the two providers that can run a document; fall back
        # rather than creating an automation nobody can save.
        provider = "openai"
    return AutomationDocument.model_validate(
        {
            "name": name or DEFAULT_NAME,
            "description": "",
            "model": {"provider": provider, "model": default_model.model},
            "trigger": {"type": "manual"},
            "steps": [],
        }
    )


# --- reads -------------------------------------------------------------------------------


async def list_automations(session: AsyncSession) -> list[Automation]:
    """Newest-first by last edit — what the list view shows."""
    return list(
        (
            await session.execute(select(Automation).order_by(Automation.updated_at.desc()))
        )
        .scalars()
        .all()
    )


async def get_automation(session: AsyncSession, automation_id: str) -> Automation:
    row = (
        await session.execute(select(Automation).where(Automation.id == automation_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Automation {automation_id} not found.")
    return row


async def current_version(
    session: AsyncSession, automation: Automation
) -> AutomationVersion | None:
    """The version row `automation.current_version_id` points at, falling back to the
    highest-numbered one (a row written before the pointer existed, or a restore that
    was interrupted)."""
    if automation.current_version_id:
        row = (
            await session.execute(
                select(AutomationVersion).where(
                    AutomationVersion.id == automation.current_version_id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return (
        await session.execute(
            select(AutomationVersion)
            .where(AutomationVersion.automation_id == automation.id)
            .order_by(AutomationVersion.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def current_version_number(session: AsyncSession, automation: Automation) -> int:
    version = await current_version(session, automation)
    return version.number if version else 0


async def list_versions(
    session: AsyncSession, automation_id: str
) -> list[AutomationVersion]:
    return list(
        (
            await session.execute(
                select(AutomationVersion)
                .where(AutomationVersion.automation_id == automation_id)
                .order_by(AutomationVersion.number.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_version(
    session: AsyncSession, automation_id: str, number: int
) -> AutomationVersion:
    row = (
        await session.execute(
            select(AutomationVersion).where(
                AutomationVersion.automation_id == automation_id,
                AutomationVersion.number == number,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Version {number} of automation {automation_id} not found.")
    return row


def parse_document(raw: Any) -> AutomationDocument:
    """Parse a client-supplied document, turning a schema mismatch into a 422.

    Used by the dry-run `POST /automations/validate`, which has no automation to attach
    a draft to and so cannot fall back to "save it anyway and report issues".
    """
    return _coerce_document(raw, created_by="json")


async def validate_draft(
    session: AsyncSession, doc: AutomationDocument
) -> tuple[AutomationDocument, list[ValidationIssue]]:
    """Validate against the live catalog without persisting anything.

    Used by `POST /automations/validate` and by `GET /automations/{id}` so a document
    saved before an integration was disconnected reports fresh issues on read.
    """
    catalog = await build_catalog(session)
    return validate_document(doc, catalog)


# --- writes ------------------------------------------------------------------------------


async def save_document(
    session: AsyncSession,
    automation: Automation,
    doc: Any,
    *,
    created_by: CreatedBy,
) -> tuple[AutomationDocument, list[ValidationIssue], int]:
    """Validate `doc`, store it as the automation's draft, and version it if it changed.

    Returns `(validated_document, issues, version_number)`. Issues are informational —
    only an unparseable document raises (and only for `created_by="json"`, as a 422).
    """
    parsed = _coerce_document(doc, created_by=created_by)
    validated, issues = await validate_draft(session, parsed)
    payload = dump_document(validated)

    version = await current_version(session, automation)
    if version is None or version.document != payload:
        number = (version.number + 1) if version is not None else 1
        version = AutomationVersion(
            id=_new_id(),
            automation_id=automation.id,
            number=number,
            document=payload,
            created_by=created_by,
            created_at=_now(),
        )
        session.add(version)
        await session.flush()
        automation.current_version_id = version.id

    automation.document = payload
    automation.name = validated.name
    automation.description = validated.description
    automation.updated_at = _now()
    await session.flush()

    scheduler.sync_job(automation)
    return validated, issues, version.number


async def create_automation(
    session: AsyncSession,
    *,
    name: str | None = None,
    document: dict[str, Any] | None = None,
) -> Automation:
    """Create an automation from `document`, or a blank draft when none is given."""
    if document is None:
        doc: Any = await _default_document(session, name)
        created_by: CreatedBy = "user"
    else:
        doc = document
        created_by = "json"

    now = _now()
    automation = Automation(
        id=_new_id(),
        name=name or DEFAULT_NAME,
        description="",
        enabled=True,
        document={},
        current_version_id=None,
        assistant_messages=[],
        last_run_id=None,
        last_run_status=None,
        created_at=now,
        updated_at=now,
    )
    session.add(automation)
    await session.flush()

    await save_document(session, automation, doc, created_by=created_by)
    log.info("automation_created", automation_id=automation.id, name=automation.name)
    return automation


async def apply_ops(
    session: AsyncSession,
    automation: Automation,
    ops: list[Operation],
    *,
    created_by: CreatedBy = "user",
) -> tuple[AutomationDocument, list[ValidationIssue], int, list[str]]:
    """Apply builder operations to the current draft and save the result.

    A malformed operation (unknown step id, out-of-range index, ...) is a client error:
    `apply_operations` raises `ValueError` and nothing is written.
    """
    old = _coerce_document(automation.document, created_by="user")
    try:
        new = apply_operations(old, ops)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc

    validated, issues, number = await save_document(
        session, automation, new, created_by=created_by
    )
    return validated, issues, number, diff_summary(old, validated)


async def restore_version(
    session: AsyncSession, automation: Automation, number: int
) -> tuple[AutomationDocument, list[ValidationIssue], int, list[str]]:
    """Make version `number` the current draft, as a new version on top of the history."""
    old = _coerce_document(automation.document, created_by="user")
    version = await get_version(session, automation.id, number)
    validated, issues, new_number = await save_document(
        session, automation, version.document, created_by="restore"
    )
    return validated, issues, new_number, diff_summary(old, validated)


async def set_enabled(
    session: AsyncSession, automation: Automation, enabled: bool
) -> Automation:
    automation.enabled = enabled
    automation.updated_at = _now()
    await session.flush()
    scheduler.sync_job(automation)
    return automation


async def rename(session: AsyncSession, automation: Automation, name: str) -> Automation:
    """Rename both the row and the document — the document's `name` is the source of
    truth everywhere else, so the two must not drift apart."""
    doc = _coerce_document(automation.document, created_by="user")
    if doc.name != name:
        await save_document(
            session, automation, doc.model_copy(update={"name": name}), created_by="user"
        )
    else:
        automation.name = name
        automation.updated_at = _now()
        await session.flush()
    return automation


async def delete_automation(session: AsyncSession, automation: Automation) -> None:
    """Delete the automation; versions, runs and run steps go with it (ON DELETE CASCADE)."""
    scheduler.remove_job(automation.id)
    await session.execute(delete(Automation).where(Automation.id == automation.id))
    log.info("automation_deleted", automation_id=automation.id)
