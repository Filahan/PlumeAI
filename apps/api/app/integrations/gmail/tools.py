"""Gmail tool functions exposed to the agent — search/get/send/modify/mark_read/trash."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.gmail.client import gmail_fetch
from app.integrations.gmail.oauth import load_creds
from app.tools.base import ToolResult, cap

# ─── OpenAI function-calling schemas ──────────────────────────────────────────────────

GMAIL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "gmail_search",
            "description": (
                "Search the authenticated user's Gmail using Gmail query syntax: from:, "
                "to:, subject:, label:INBOX, is:unread, has:attachment, newer_than:1d, "
                "older_than:7d, after:YYYY/MM/DD, before:YYYY/MM/DD. "
                "IMPORTANT: dates MUST be concrete YYYY/MM/DD (Gmail does NOT understand the "
                "words 'today', 'yesterday' or 'now'). "
                "Returns matching message ids and short metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query."},
                    "max_results": {
                        "type": "number",
                        "description": "Max messages to return (1-100, default 25).",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_get",
            "description": "Fetch a single Gmail message (subject, from, to, date, body) by id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Message id."}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_send",
            "description": "Send an email from the authenticated user's Gmail account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email(s), comma-separated."},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Plain text body."},
                    "cc": {"type": "string"},
                    "bcc": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_modify",
            "description": "Add or remove Gmail labels on a message (INBOX, STARRED, UNREAD, TRASH, custom).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "add_labels": {"type": "array", "items": {"type": "string"}},
                    "remove_labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_mark_read",
            "description": "Mark a Gmail message as read or unread.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "read": {"type": "boolean"},
                },
                "required": ["id", "read"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_trash",
            "description": "Move a Gmail message to trash (recoverable for 30 days).",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
]

GMAIL_FUNCTION_NAMES = {s["function"]["name"] for s in GMAIL_SCHEMAS}


# ─── helpers ──────────────────────────────────────────────────────────────────────────


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _header(headers: list[dict[str, str]] | None, name: str) -> str:
    if not headers:
        return ""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(part: dict[str, Any] | None) -> str:
    if part is None:
        return ""
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if mime == "text/plain" and data:
        try:
            return _b64url_decode(data).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    for child in part.get("parts", []):
        out = _extract_body(child)
        if out:
            return out
    if mime == "text/html" and data:
        # Crude fallback: strip tags from the html body.
        import re

        raw = _b64url_decode(data).decode("utf-8", errors="replace")
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
    return ""


def _rfc5322(to: str, subject: str, body: str, cc: str | None, bcc: str | None) -> str:
    lines = [f"To: {to}"]
    if cc:
        lines.append(f"Cc: {cc}")
    if bcc:
        lines.append(f"Bcc: {bcc}")
    lines += [
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
    ]
    return "\r\n".join(lines)


# ─── tool implementations ────────────────────────────────────────────────────────────


async def _gmail_search(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return ToolResult(ok=False, content='gmail_search requires "query".')
    raw_max = args.get("max_results", 25)
    max_results = max(1, min(int(raw_max) if isinstance(raw_max, (int, float)) else 25, 100))

    q = urlencode({"maxResults": max_results, "q": query})
    r = await gmail_fetch(session, f"/users/me/messages?{q}")
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_search HTTP {r.status_code}: {cap(r.text)}")
    data = r.json()
    messages = data.get("messages") or []
    if not messages:
        return ToolResult(ok=True, content="No messages matched.")

    import asyncio

    async def _meta(mid: str) -> dict[str, str]:
        path = (
            f"/users/me/messages/{mid}?format=metadata"
            "&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date"
        )
        rr = await gmail_fetch(session, path)
        if not rr.is_success:
            return {"id": mid, "error": f"HTTP {rr.status_code}"}
        body = rr.json()
        headers = body.get("payload", {}).get("headers", [])
        return {
            "id": mid,
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
            "snippet": body.get("snippet", ""),
        }

    metas = await asyncio.gather(*(_meta(m["id"]) for m in messages[:max_results]))
    lines: list[str] = []
    for i, m in enumerate(metas, 1):
        if "error" in m:
            lines.append(f"{i}. [{m['id']}] ({m['error']})")
        else:
            lines.append(
                f"{i}. [{m['id']}] {m.get('subject') or '(no subject)'}\n"
                f"   from: {m.get('from')}\n"
                f"   date: {m.get('date')}\n"
                f"   {m.get('snippet')}"
            )
    return ToolResult(ok=True, content=cap("\n\n".join(lines)))


async def _gmail_get(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_get requires "id".')
    r = await gmail_fetch(session, f"/users/me/messages/{mid}?format=full")
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_get HTTP {r.status_code}: {cap(r.text)}")
    j = r.json()
    payload = j.get("payload", {})
    headers = payload.get("headers", [])
    body = _extract_body(payload) or j.get("snippet", "")
    text = "\n".join(
        [
            f"Subject: {_header(headers, 'Subject')}",
            f"From: {_header(headers, 'From')}",
            f"To: {_header(headers, 'To')}",
            f"Date: {_header(headers, 'Date')}",
            f"Labels: {', '.join(j.get('labelIds', []))}",
            "",
            body,
        ]
    )
    return ToolResult(ok=True, content=cap(text))


async def _gmail_send(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")
    if not (isinstance(to, str) and isinstance(subject, str) and isinstance(body, str)):
        return ToolResult(ok=False, content='gmail_send requires "to", "subject", "body".')
    raw = _b64url_encode(_rfc5322(to, subject, body, args.get("cc"), args.get("bcc")).encode("utf-8"))
    r = await gmail_fetch(session, "/users/me/messages/send", "POST", {"raw": raw})
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_send HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Sent. id={r.json().get('id')}")


async def _gmail_modify(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_modify requires "id".')
    add = [s for s in (args.get("add_labels") or []) if isinstance(s, str)]
    rem = [s for s in (args.get("remove_labels") or []) if isinstance(s, str)]
    if not add and not rem:
        return ToolResult(ok=False, content="gmail_modify requires add_labels or remove_labels.")
    payload = {"addLabelIds": add, "removeLabelIds": rem}
    r = await gmail_fetch(session, f"/users/me/messages/{mid}/modify", "POST", payload)
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_modify HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(
        ok=True,
        content=f"Modified {mid}. add={','.join(add) or '-'} remove={','.join(rem) or '-'}",
    )


async def _gmail_mark_read(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    mid = args.get("id")
    read = args.get("read")
    if not isinstance(mid, str) or not isinstance(read, bool):
        return ToolResult(ok=False, content='gmail_mark_read requires "id" and boolean "read".')
    return await _gmail_modify(
        {
            "id": mid,
            "add_labels": [] if read else ["UNREAD"],
            "remove_labels": ["UNREAD"] if read else [],
        },
        session,
    )


async def _gmail_trash(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_trash requires "id".')
    r = await gmail_fetch(session, f"/users/me/messages/{mid}/trash", "POST")
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_trash HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Trashed {mid}.")


_DISPATCH = {
    "gmail_search": _gmail_search,
    "gmail_get": _gmail_get,
    "gmail_send": _gmail_send,
    "gmail_modify": _gmail_modify,
    "gmail_mark_read": _gmail_mark_read,
    "gmail_trash": _gmail_trash,
}


# ─── Integration object ──────────────────────────────────────────────────────────────


class GmailIntegration:
    name = "gmail"
    label = "Gmail"
    description = "Read, send, label, and trash Gmail messages."
    setup_url = "/api/tools/gmail/oauth/start"
    schemas = GMAIL_SCHEMAS

    async def is_configured(self, session: AsyncSession) -> bool:
        return (await load_creds(session)) is not None

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult:
        fn = _DISPATCH.get(function_name)
        if fn is None:
            return ToolResult(ok=False, content=f"Unknown gmail function: {function_name}")
        try:
            return await fn(args, session)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content=f"Error: {exc}")


gmail_integration = GmailIntegration()
