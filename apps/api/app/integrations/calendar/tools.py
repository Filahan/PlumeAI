"""Google Calendar tool functions: list/get/create/update/delete events."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google.base import GoogleOAuthIntegration
from app.tools.base import ToolResult, cap

# ─── OpenAI function-calling schemas ──────────────────────────────────────────────────

_DATE_NOTE = (
    "IMPORTANT: dates MUST be concrete RFC3339 strings — either "
    "'YYYY-MM-DDTHH:MM:SS' with a timezone offset (e.g. '2026-06-04T14:00:00+02:00') "
    "for timed events, or 'YYYY-MM-DD' for all-day events. Never use the literal words "
    "'today', 'tomorrow', 'now' — Google rejects them."
)

CALENDAR_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calendar_list_events",
            "description": (
                "List events from a calendar within a time window. Returns id, summary, "
                "start, end, location, attendees count. "
                + _DATE_NOTE
                + " Defaults: time_min=now, time_max=now+7d, calendar_id='primary'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "RFC3339 lower bound (inclusive). Defaults to now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "RFC3339 upper bound (exclusive). Defaults to now + 7 days.",
                    },
                    "q": {
                        "type": "string",
                        "description": "Free-text search across event fields (summary, description, attendees, location).",
                    },
                    "max_results": {
                        "type": "number",
                        "description": "Max events to return (1-100, default 25).",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar id (default 'primary').",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_get_event",
            "description": "Fetch a single Calendar event by id (full details).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Event id."},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar id (default 'primary').",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create_event",
            "description": (
                "Create a Calendar event. Use timed format ('YYYY-MM-DDTHH:MM:SS' with TZ "
                "offset) OR all-day format ('YYYY-MM-DD'). "
                + _DATE_NOTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title."},
                    "start": {"type": "string", "description": "RFC3339 datetime OR YYYY-MM-DD for all-day."},
                    "end": {"type": "string", "description": "RFC3339 datetime OR YYYY-MM-DD for all-day."},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar id (default 'primary').",
                    },
                },
                "required": ["summary", "start", "end"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_update_event",
            "description": (
                "Update fields of an existing event. Only the fields you pass are changed. "
                + _DATE_NOTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Event id."},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar id (default 'primary').",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_delete_event",
            "description": "Delete a Calendar event permanently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Event id."},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar id (default 'primary').",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]


# ─── helpers ──────────────────────────────────────────────────────────────────────────


_TZ_OFFSET_RE = re.compile(r"[+-]\d{2}:?\d{2}$")


def _normalize_rfc3339(value: str | None) -> str | None:
    """Be lenient on what the LLM sends:
    - `YYYY-MM-DD` → expand to `YYYY-MM-DDT00:00:00Z`
    - `YYYY-MM-DDTHH:MM:SS` without offset → append `Z` (assume UTC)
    - already has `Z` or `+HH:MM` offset → keep as-is
    Returns None if value is empty/None.
    """
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v.endswith("Z") or _TZ_OFFSET_RE.search(v):
        return v
    if "T" not in v and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v + "T00:00:00Z"
    if "T" in v:
        return v + "Z"
    return v


def _format_when(point: dict[str, Any]) -> str:
    """Render a Google `EventDateTime` (either `date` for all-day or `dateTime`)."""
    if not point:
        return "-"
    return str(point.get("dateTime") or point.get("date") or "-")


def _datetime_obj(value: str) -> dict[str, str]:
    """`YYYY-MM-DD` → all-day `{"date": ...}`, otherwise `{"dateTime": ...}`."""
    if len(value) == 10 and value.count("-") == 2 and "T" not in value:
        return {"date": value}
    return {"dateTime": value}


def _attendees_obj(emails: list[str] | None) -> list[dict[str, str]] | None:
    if not emails:
        return None
    return [{"email": e} for e in emails if isinstance(e, str) and e]


def _patch_event_body(args: dict[str, Any]) -> dict[str, Any]:
    """Build a PATCH/POST body, only including fields the caller provided."""
    body: dict[str, Any] = {}
    if "summary" in args and isinstance(args["summary"], str):
        body["summary"] = args["summary"]
    if "description" in args and isinstance(args["description"], str):
        body["description"] = args["description"]
    if "location" in args and isinstance(args["location"], str):
        body["location"] = args["location"]
    if "start" in args and isinstance(args["start"], str):
        body["start"] = _datetime_obj(args["start"])
    if "end" in args and isinstance(args["end"], str):
        body["end"] = _datetime_obj(args["end"])
    attendees = _attendees_obj(args.get("attendees"))
    if attendees is not None:
        body["attendees"] = attendees
    return body


def _format_event_row(i: int, e: dict[str, Any]) -> str:
    summary = e.get("summary") or "(no title)"
    start = _format_when(e.get("start", {}))
    end = _format_when(e.get("end", {}))
    location = e.get("location")
    attendees = e.get("attendees") or []
    lines = [
        f"{i}. [{e.get('id')}] {summary}",
        f"   when: {start} → {end}",
    ]
    if location:
        lines.append(f"   where: {location}")
    if attendees:
        lines.append(f"   attendees: {len(attendees)}")
    return "\n".join(lines)


# ─── tool implementations ────────────────────────────────────────────────────────────


async def _calendar_list_events(
    self: "CalendarIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    calendar_id = args.get("calendar_id") or "primary"
    raw_max = args.get("max_results", 25)
    max_results = max(1, min(int(raw_max) if isinstance(raw_max, (int, float)) else 25, 100))

    now = datetime.now(timezone.utc)
    time_min = _normalize_rfc3339(args.get("time_min")) or now.isoformat()
    time_max = _normalize_rfc3339(args.get("time_max")) or (now + timedelta(days=7)).isoformat()

    params: dict[str, Any] = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    q = args.get("q")
    if isinstance(q, str) and q:
        params["q"] = q

    r = await self.authed_fetch(session, f"/calendars/{calendar_id}/events", params=params)
    if not r.is_success:
        return ToolResult(ok=False, content=f"calendar_list_events HTTP {r.status_code}: {cap(r.text)}")
    events = r.json().get("items", [])
    if not events:
        return ToolResult(ok=True, content="No events in the requested window.")
    lines = [_format_event_row(i, e) for i, e in enumerate(events, 1)]
    return ToolResult(ok=True, content=cap("\n\n".join(lines)))


async def _calendar_get_event(
    self: "CalendarIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    eid = args.get("id")
    if not isinstance(eid, str):
        return ToolResult(ok=False, content='calendar_get_event requires "id".')
    calendar_id = args.get("calendar_id") or "primary"
    r = await self.authed_fetch(session, f"/calendars/{calendar_id}/events/{eid}")
    if not r.is_success:
        return ToolResult(ok=False, content=f"calendar_get_event HTTP {r.status_code}: {cap(r.text)}")
    e = r.json()
    attendees = e.get("attendees") or []
    text = "\n".join(
        [
            f"Summary: {e.get('summary') or '(no title)'}",
            f"Status: {e.get('status')}",
            f"Start: {_format_when(e.get('start', {}))}",
            f"End: {_format_when(e.get('end', {}))}",
            f"Location: {e.get('location') or '-'}",
            f"Organizer: {(e.get('organizer') or {}).get('email') or '-'}",
            f"Attendees: {', '.join((a.get('email') or '') for a in attendees) or '-'}",
            f"Link: {e.get('htmlLink') or '-'}",
            "",
            e.get("description") or "(no description)",
        ]
    )
    return ToolResult(ok=True, content=cap(text))


async def _calendar_create_event(
    self: "CalendarIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    summary = args.get("summary")
    start = args.get("start")
    end = args.get("end")
    if not (isinstance(summary, str) and isinstance(start, str) and isinstance(end, str)):
        return ToolResult(
            ok=False,
            content='calendar_create_event requires "summary", "start", "end".',
        )
    calendar_id = args.get("calendar_id") or "primary"
    body = _patch_event_body({**args, "summary": summary, "start": start, "end": end})
    r = await self.authed_fetch(session, f"/calendars/{calendar_id}/events", "POST", body)
    if not r.is_success:
        return ToolResult(ok=False, content=f"calendar_create_event HTTP {r.status_code}: {cap(r.text)}")
    j = r.json()
    return ToolResult(
        ok=True,
        content=f"Created. id={j.get('id')} link={j.get('htmlLink')}",
    )


async def _calendar_update_event(
    self: "CalendarIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    eid = args.get("id")
    if not isinstance(eid, str):
        return ToolResult(ok=False, content='calendar_update_event requires "id".')
    calendar_id = args.get("calendar_id") or "primary"
    body = _patch_event_body(args)
    if not body:
        return ToolResult(ok=False, content="calendar_update_event needs at least one field to update.")
    r = await self.authed_fetch(session, f"/calendars/{calendar_id}/events/{eid}", "PATCH", body)
    if not r.is_success:
        return ToolResult(ok=False, content=f"calendar_update_event HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Updated {eid}.")


async def _calendar_delete_event(
    self: "CalendarIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    eid = args.get("id")
    if not isinstance(eid, str):
        return ToolResult(ok=False, content='calendar_delete_event requires "id".')
    calendar_id = args.get("calendar_id") or "primary"
    r = await self.authed_fetch(session, f"/calendars/{calendar_id}/events/{eid}", "DELETE")
    if not r.is_success and r.status_code != 410:
        # 410 Gone is fine — already deleted.
        return ToolResult(ok=False, content=f"calendar_delete_event HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Deleted {eid}.")


# ─── Integration object ──────────────────────────────────────────────────────────────


class CalendarIntegration(GoogleOAuthIntegration):
    name = "calendar"
    label = "Google Calendar"
    description = "Read, create, update, and delete events on Google Calendar."
    setup_url = "/api/tools/calendar/oauth/start"
    schemas = CALENDAR_SCHEMAS

    tool_key = "calendar"
    scopes = "https://www.googleapis.com/auth/calendar.events"
    api_base_url = "https://www.googleapis.com/calendar/v3"

    @property
    def _dispatch(self):
        return {
            "calendar_list_events": _calendar_list_events,
            "calendar_get_event": _calendar_get_event,
            "calendar_create_event": _calendar_create_event,
            "calendar_update_event": _calendar_update_event,
            "calendar_delete_event": _calendar_delete_event,
        }


calendar_integration = CalendarIntegration()
