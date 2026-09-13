"""Gmail tool functions: search/get/send/modify/mark_read/trash."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import ActionMeta
from app.integrations.google.base import GoogleOAuthIntegration
from app.tools.base import ToolResult, cap

# ─── Setup guide + catalog metadata (ported from apps/web/src/lib/tools/registry-client.ts) ──

GOOGLE_SETUP: dict[str, Any] = {
    "intro": (
        "Uses Google OAuth — set up the OAuth client once, share it across every "
        "Google integration."
    ),
    "steps": [
        {
            "title": "Create an OAuth client in Google Cloud Console",
            "description": (
                'Pick "Web application" as the type. Reuse an existing client if you have one.'
            ),
            "link": {
                "label": "Open Credentials",
                "url": "https://console.cloud.google.com/apis/credentials",
            },
        },
        {
            "title": 'Add this URL to your OAuth client\'s "Authorized redirect URIs"',
            "copy": {
                "label": "Authorized redirect URI",
                "value": "__ORIGIN__/api/tools/google/oauth/callback",
            },
        },
        {
            "title": (
                "Paste the generated Client ID and Client Secret into the Credentials "
                "section above"
            ),
            "description": (
                "One credential pair unlocks Gmail, Drive, Calendar, and every future "
                "Google integration."
            ),
        },
    ],
}

GMAIL_ACTION_META: dict[str, ActionMeta] = {
    "gmail_search": ActionMeta(
        label="Search emails",
        output_description="Matching messages with id, sender, subject, date, and snippet.",
    ),
    "gmail_get": ActionMeta(
        label="Get an email",
        output_description="Full message: subject, from, to, date, labels, and body.",
    ),
    "gmail_send": ActionMeta(
        label="Send an email",
        output_description="Confirmation with the sent message id.",
    ),
    "gmail_modify": ActionMeta(
        label="Add or remove labels",
        output_description="Confirmation of the labels added and removed.",
    ),
    "gmail_mark_read": ActionMeta(
        label="Mark read or unread",
        output_description="Confirmation of the read/unread state change.",
    ),
    "gmail_trash": ActionMeta(
        label="Trash an email",
        output_description="Confirmation the message was moved to trash.",
    ),
}

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


# ─── tool implementations (free functions, take the integration as `self`) ──────────


async def _gmail_search(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return ToolResult(ok=False, content='gmail_search requires "query".')
    raw_max = args.get("max_results", 25)
    max_results = max(1, min(int(raw_max) if isinstance(raw_max, (int, float)) else 25, 100))

    r = await self.authed_fetch(
        session, "/users/me/messages", params={"maxResults": max_results, "q": query}
    )
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_search HTTP {r.status_code}: {cap(r.text)}")
    data = r.json()
    messages = data.get("messages") or []
    if not messages:
        return ToolResult(ok=True, content="No messages matched.")

    async def _meta(mid: str) -> dict[str, str]:
        rr = await self.authed_fetch(
            session,
            f"/users/me/messages/{mid}",
            params={
                "format": "metadata",
                "metadataHeaders": ["Subject", "From", "Date"],
            },
        )
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


async def _gmail_get(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_get requires "id".')
    r = await self.authed_fetch(session, f"/users/me/messages/{mid}", params={"format": "full"})
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


async def _gmail_send(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")
    if not (isinstance(to, str) and isinstance(subject, str) and isinstance(body, str)):
        return ToolResult(ok=False, content='gmail_send requires "to", "subject", "body".')
    raw = _b64url_encode(_rfc5322(to, subject, body, args.get("cc"), args.get("bcc")).encode("utf-8"))
    r = await self.authed_fetch(session, "/users/me/messages/send", "POST", {"raw": raw})
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_send HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Sent. id={r.json().get('id')}")


async def _gmail_modify(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_modify requires "id".')
    add = [s for s in (args.get("add_labels") or []) if isinstance(s, str)]
    rem = [s for s in (args.get("remove_labels") or []) if isinstance(s, str)]
    if not add and not rem:
        return ToolResult(ok=False, content="gmail_modify requires add_labels or remove_labels.")
    payload = {"addLabelIds": add, "removeLabelIds": rem}
    r = await self.authed_fetch(session, f"/users/me/messages/{mid}/modify", "POST", payload)
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_modify HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(
        ok=True,
        content=f"Modified {mid}. add={','.join(add) or '-'} remove={','.join(rem) or '-'}",
    )


async def _gmail_mark_read(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    mid = args.get("id")
    read = args.get("read")
    if not isinstance(mid, str) or not isinstance(read, bool):
        return ToolResult(ok=False, content='gmail_mark_read requires "id" and boolean "read".')
    return await _gmail_modify(
        self,
        {
            "id": mid,
            "add_labels": [] if read else ["UNREAD"],
            "remove_labels": ["UNREAD"] if read else [],
        },
        session,
    )


async def _gmail_trash(
    self: "GmailIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    mid = args.get("id")
    if not isinstance(mid, str):
        return ToolResult(ok=False, content='gmail_trash requires "id".')
    r = await self.authed_fetch(session, f"/users/me/messages/{mid}/trash", "POST")
    if not r.is_success:
        return ToolResult(ok=False, content=f"gmail_trash HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Trashed {mid}.")


# ─── Integration object ──────────────────────────────────────────────────────────────


class GmailIntegration(GoogleOAuthIntegration):
    name = "gmail"
    label = "Gmail"
    description = "Read, send, label, and trash Gmail messages."
    setup_url = "/api/tools/gmail/oauth/start"
    schemas = GMAIL_SCHEMAS

    logo_url = "https://cdn.simpleicons.org/gmail"
    connect_mode = "oauth"
    setup = GOOGLE_SETUP
    action_meta = GMAIL_ACTION_META

    tool_key = "gmail"
    scopes = " ".join(
        [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.labels",
        ]
    )
    api_base_url = "https://gmail.googleapis.com/gmail/v1"

    @property
    def _dispatch(self):
        return {
            "gmail_search": _gmail_search,
            "gmail_get": _gmail_get,
            "gmail_send": _gmail_send,
            "gmail_modify": _gmail_modify,
            "gmail_mark_read": _gmail_mark_read,
            "gmail_trash": _gmail_trash,
        }


gmail_integration = GmailIntegration()
