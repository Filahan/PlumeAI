"""Google Drive tool functions: search/get/list/create_doc/trash."""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google.base import GoogleOAuthIntegration
from app.integrations.google.oauth import get_valid_access_token
from app.tools.base import TIMEOUT_SECONDS, ToolResult, cap

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDE_MIME = "application/vnd.google-apps.presentation"

UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

# ─── OpenAI function-calling schemas ──────────────────────────────────────────────────

DRIVE_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "drive_search",
            "description": (
                "Search files on Google Drive using Drive query syntax. Examples: "
                "`name contains 'roadmap'`, `mimeType='application/vnd.google-apps.document'`, "
                "`trashed=false`, `modifiedTime > '2025-01-01T00:00:00'`. "
                "Combine with `and` / `or`. Returns id, name, mimeType, modifiedTime."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Drive query."},
                    "max_results": {
                        "type": "number",
                        "description": "Max files to return (1-100, default 25).",
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
            "name": "drive_get",
            "description": (
                "Fetch a Drive file by id: metadata + plain-text content. Google Docs / "
                "Sheets / Slides are exported as text/plain. Returns name, mimeType, body."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "File id."}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_list",
            "description": (
                "List immediate children of a folder. If `folder_id` is omitted, lists files "
                "in the root of My Drive. Returns id, name, mimeType, modifiedTime."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Folder id (omit for the root of My Drive).",
                    },
                    "max_results": {
                        "type": "number",
                        "description": "Max files to return (1-100, default 25).",
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
            "name": "drive_create_doc",
            "description": "Create a Google Doc with the given title and plain-text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Plain-text body."},
                },
                "required": ["title", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_trash",
            "description": "Move a Drive file to the trash (recoverable for 30 days).",
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


def _format_file_row(i: int, f: dict[str, Any]) -> str:
    return (
        f"{i}. [{f.get('id')}] {f.get('name') or '(unnamed)'}\n"
        f"   mime: {f.get('mimeType')}\n"
        f"   modified: {f.get('modifiedTime')}"
    )


def _is_google_native(mime: str) -> bool:
    return mime.startswith("application/vnd.google-apps.")


# ─── tool implementations ────────────────────────────────────────────────────────────


async def _drive_search(
    self: "DriveIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return ToolResult(ok=False, content='drive_search requires "query".')
    raw_max = args.get("max_results", 25)
    max_results = max(1, min(int(raw_max) if isinstance(raw_max, (int, float)) else 25, 100))

    r = await self.authed_fetch(
        session,
        "/files",
        params={
            "q": query,
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,modifiedTime)",
        },
    )
    if not r.is_success:
        return ToolResult(ok=False, content=f"drive_search HTTP {r.status_code}: {cap(r.text)}")
    files = r.json().get("files", [])
    if not files:
        return ToolResult(ok=True, content="No files matched.")
    lines = [_format_file_row(i, f) for i, f in enumerate(files, 1)]
    return ToolResult(ok=True, content=cap("\n\n".join(lines)))


async def _drive_list(
    self: "DriveIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    folder_id = args.get("folder_id") or "root"
    raw_max = args.get("max_results", 25)
    max_results = max(1, min(int(raw_max) if isinstance(raw_max, (int, float)) else 25, 100))

    # Escape single quotes in the folder id (rare but safe).
    safe_folder = str(folder_id).replace("'", "\\'")
    r = await self.authed_fetch(
        session,
        "/files",
        params={
            "q": f"'{safe_folder}' in parents and trashed=false",
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,modifiedTime)",
        },
    )
    if not r.is_success:
        return ToolResult(ok=False, content=f"drive_list HTTP {r.status_code}: {cap(r.text)}")
    files = r.json().get("files", [])
    if not files:
        return ToolResult(ok=True, content=f"Folder {folder_id} is empty.")
    lines = [_format_file_row(i, f) for i, f in enumerate(files, 1)]
    return ToolResult(ok=True, content=cap("\n\n".join(lines)))


async def _drive_get(
    self: "DriveIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    fid = args.get("id")
    if not isinstance(fid, str):
        return ToolResult(ok=False, content='drive_get requires "id".')

    meta = await self.authed_fetch(
        session, f"/files/{fid}", params={"fields": "id,name,mimeType,modifiedTime,size"}
    )
    if not meta.is_success:
        return ToolResult(ok=False, content=f"drive_get HTTP {meta.status_code}: {cap(meta.text)}")
    m = meta.json()
    mime = m.get("mimeType", "")

    if _is_google_native(mime):
        body_r = await self.authed_fetch(
            session, f"/files/{fid}/export", params={"mimeType": "text/plain"}
        )
    else:
        body_r = await self.authed_fetch(session, f"/files/{fid}", params={"alt": "media"})

    body_text = body_r.text if body_r.is_success else f"(could not read body: HTTP {body_r.status_code})"
    out = "\n".join(
        [
            f"Name: {m.get('name')}",
            f"MimeType: {mime}",
            f"Modified: {m.get('modifiedTime')}",
            "",
            body_text,
        ]
    )
    return ToolResult(ok=True, content=cap(out))


async def _drive_create_doc(
    self: "DriveIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    title = args.get("title")
    content = args.get("content")
    if not (isinstance(title, str) and isinstance(content, str)):
        return ToolResult(ok=False, content='drive_create_doc requires "title" and "content".')

    # Multipart upload: one request with metadata (mimeType=Doc → Drive converts) + text body.
    boundary = "plumeai_drive_boundary_42"
    metadata = {"name": title, "mimeType": GOOGLE_DOC_MIME}
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    )

    token = await get_valid_access_token(session, self.tool_key)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.post(
            UPLOAD_URL,
            params={"uploadType": "multipart"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body.encode("utf-8"),
        )
    if not r.is_success:
        return ToolResult(ok=False, content=f"drive_create_doc HTTP {r.status_code}: {cap(r.text)}")
    j = r.json()
    return ToolResult(ok=True, content=f"Created Doc. id={j.get('id')} name={j.get('name')}")


async def _drive_trash(
    self: "DriveIntegration", args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    fid = args.get("id")
    if not isinstance(fid, str):
        return ToolResult(ok=False, content='drive_trash requires "id".')
    r = await self.authed_fetch(session, f"/files/{fid}", "PATCH", {"trashed": True})
    if not r.is_success:
        return ToolResult(ok=False, content=f"drive_trash HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Trashed {fid}.")


# ─── Integration object ──────────────────────────────────────────────────────────────


class DriveIntegration(GoogleOAuthIntegration):
    name = "drive"
    label = "Google Drive"
    description = "Search, read, list, create, and trash files on Google Drive."
    setup_url = "/api/tools/drive/oauth/start"
    schemas = DRIVE_SCHEMAS

    tool_key = "drive"
    scopes = "https://www.googleapis.com/auth/drive"
    api_base_url = "https://www.googleapis.com/drive/v3"

    @property
    def _dispatch(self):
        return {
            "drive_search": _drive_search,
            "drive_get": _drive_get,
            "drive_list": _drive_list,
            "drive_create_doc": _drive_create_doc,
            "drive_trash": _drive_trash,
        }


drive_integration = DriveIntegration()
