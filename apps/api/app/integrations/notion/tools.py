"""Notion tool functions: search / get_page / create_page / append_blocks / query_database.

Auth is one internal integration secret stored encrypted in DB
(`tool_credentials["notion"]`) and entered through the Tools UI. Notion only exposes
pages that have been explicitly shared with the integration, so every "not found" is
much more often a sharing problem than a wrong id — the error messages say so.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolError
from app.integrations.base import CredentialField, Integration
from app.integrations.notion.blocks import (
    MAX_BLOCKS_PER_REQUEST,
    blocks_to_text,
    markdown_to_blocks,
)
from app.integrations.notion.client import (
    CREDENTIALS_NAMESPACE,
    extract_title,
    flatten_properties,
    notion_call,
)
from app.integrations.notion.schemas import (
    NOTION_ACTION_META,
    NOTION_SCHEMAS,
    NOTION_SETUP,
)
from app.services.tool_credentials import get_credentials
from app.tools.base import ToolResult, cap

MAX_READ_BLOCKS = 200
# Notion ids are 32 hex chars, dashed or not. Anchored at the end so a pasted URL's
# slug ("…/Design-doc-<id>") cannot contribute its own hex letters to the match.
_ID_RE = re.compile(r"([0-9a-fA-F]{32})$")
_PERMANENT = {"retryable": False}


def _clamp(raw: Any, default: int, high: int) -> int:
    value = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default
    return max(1, min(value, high))


def _clean_id(raw: Any, field: str) -> str:
    """Accept a dashed id, a plain 32-char id, or a pasted Notion URL."""
    text = str(raw or "").strip()
    if not text:
        raise ToolError(f'Missing "{field}".', extra=dict(_PERMANENT))
    tail = text.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    match = _ID_RE.search(tail.replace("-", ""))
    return match.group(1) if match else text


# ─── search ──────────────────────────────────────────────────────────────────────────


async def _notion_search(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult(ok=False, content='notion_search requires "query".', retryable=False)
    limit = _clamp(args.get("limit"), 10, 50)
    body: dict[str, Any] = {"query": query.strip(), "page_size": limit}
    kind = args.get("filter")
    if kind in ("page", "database"):
        body["filter"] = {"property": "object", "value": kind}

    payload = await notion_call(session, "POST", "/v1/search", json_body=body)
    results: list[dict[str, Any]] = []
    for item in (payload.get("results") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "id": str(item.get("id") or ""),
                "object": str(item.get("object") or ""),
                "title": extract_title(item),
                "url": str(item.get("url") or ""),
                "last_edited_time": str(item.get("last_edited_time") or ""),
            }
        )

    data = {"results": results, "count": len(results)}
    if not results:
        return ToolResult(
            ok=True,
            content=(
                "Nothing matched. Remember Notion only searches pages shared with the "
                "integration (page → … → Connections)."
            ),
            data=data,
        )
    lines = [
        f"{i}. [{r['id']}] {r['title']} ({r['object']})\n   {r['url']}\n"
        f"   edited {r['last_edited_time']}"
        for i, r in enumerate(results, 1)
    ]
    return ToolResult(ok=True, content=cap("\n\n".join(lines)), data=data)


# ─── get_page ────────────────────────────────────────────────────────────────────────


async def _fetch_children(session: AsyncSession, block_id: str) -> list[dict[str, Any]]:
    """`/v1/blocks/{id}/children`, following `next_cursor` up to MAX_READ_BLOCKS blocks."""
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(out) < MAX_READ_BLOCKS:
        params: dict[str, Any] = {"page_size": min(100, MAX_READ_BLOCKS - len(out))}
        if cursor:
            params["start_cursor"] = cursor
        payload = await notion_call(
            session, "GET", f"/v1/blocks/{block_id}/children", params=params
        )
        out.extend(b for b in (payload.get("results") or []) if isinstance(b, dict))
        cursor = payload.get("next_cursor") if payload.get("has_more") else None
        if not cursor:
            break
    return out


async def _notion_get_page(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    page_id = _clean_id(args.get("page_id"), "page_id")
    page = await notion_call(session, "GET", f"/v1/pages/{page_id}")
    title = extract_title(page)
    properties = flatten_properties(page.get("properties"))
    content = blocks_to_text(await _fetch_children(session, page_id))

    data = {
        "id": str(page.get("id") or page_id),
        "title": title,
        "url": str(page.get("url") or ""),
        "properties": properties,
        "content": content,
    }
    # The title already heads the text; skip the property that just repeats it.
    prop_lines = "\n".join(f"{k}: {v}" for k, v in properties.items() if v != title)
    text = f"# {title}\n" + (f"\n{prop_lines}\n" if prop_lines else "") + f"\n{content}"
    return ToolResult(ok=True, content=cap(text.strip()), data=data)


# ─── create_page ─────────────────────────────────────────────────────────────────────


async def _database_title_property(session: AsyncSession, database_id: str) -> str:
    """Name of the database's title column — Notion requires the real property name."""
    db = await notion_call(session, "GET", f"/v1/databases/{database_id}")
    props = db.get("properties")
    if isinstance(props, dict):
        for name, prop in props.items():
            if isinstance(prop, dict) and prop.get("type") == "title":
                return str(name)
    return "Name"


def _title_property(title: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": title[:2000]}}]}


async def _append_children(
    session: AsyncSession, block_id: str, children: list[dict[str, Any]]
) -> int:
    """PATCH children in ≤100-block batches (Notion's per-request cap). Returns the count."""
    appended = 0
    for start in range(0, len(children), MAX_BLOCKS_PER_REQUEST):
        batch = children[start : start + MAX_BLOCKS_PER_REQUEST]
        await notion_call(
            session,
            "PATCH",
            f"/v1/blocks/{block_id}/children",
            json_body={"children": batch},
        )
        appended += len(batch)
    return appended


async def _notion_create_page(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    parent_id = _clean_id(args.get("parent_id"), "parent_id")
    raw_parent_type = args.get("parent_type")
    parent_type = raw_parent_type if raw_parent_type in ("page", "database") else "page"
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        return ToolResult(ok=False, content='notion_create_page requires "title".', retryable=False)

    if parent_type == "database":
        parent = {"database_id": parent_id}
        title_key = await _database_title_property(session, parent_id)
    else:
        parent = {"page_id": parent_id}
        title_key = "title"

    properties: dict[str, Any] = {title_key: _title_property(title.strip())}
    extra = args.get("properties")
    if isinstance(extra, dict):
        for key, value in extra.items():
            if isinstance(value, dict):
                properties[str(key)] = value

    children = markdown_to_blocks(args.get("content") or "")
    body: dict[str, Any] = {"parent": parent, "properties": properties}
    if children:
        body["children"] = children[:MAX_BLOCKS_PER_REQUEST]

    page = await notion_call(session, "POST", "/v1/pages", json_body=body)
    page_id = str(page.get("id") or "")
    overflow = children[MAX_BLOCKS_PER_REQUEST:]
    if overflow and page_id:
        await _append_children(session, page_id, overflow)

    data = {"id": page_id, "url": str(page.get("url") or ""), "title": title.strip()}
    summary = f'Created "{title.strip()}" ({len(children)} blocks). id={page_id}'
    return ToolResult(ok=True, content=f"{summary} {data['url']}".strip(), data=data)


# ─── append_blocks ───────────────────────────────────────────────────────────────────


async def _notion_append_blocks(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    page_id = _clean_id(args.get("page_id"), "page_id")
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        return ToolResult(
            ok=False, content='notion_append_blocks requires non-empty "content".', retryable=False
        )
    children = markdown_to_blocks(content)
    if not children:
        return ToolResult(ok=False, content="Nothing to append.", retryable=False)
    appended = await _append_children(session, page_id, children)
    return ToolResult(
        ok=True, content=f"Appended {appended} block(s) to {page_id}.", data={"appended": appended}
    )


# ─── query_database ──────────────────────────────────────────────────────────────────


async def _notion_query_database(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    database_id = _clean_id(args.get("database_id"), "database_id")
    page_size = _clamp(args.get("page_size"), 25, 100)
    body: dict[str, Any] = {"page_size": page_size}
    if isinstance(args.get("filter"), dict) and args["filter"]:
        body["filter"] = args["filter"]
    if isinstance(args.get("sorts"), list) and args["sorts"]:
        body["sorts"] = args["sorts"]

    payload = await notion_call(
        session, "POST", f"/v1/databases/{database_id}/query", json_body=body
    )
    results: list[dict[str, Any]] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        results.append(
            {
                "id": str(row.get("id") or ""),
                "url": str(row.get("url") or ""),
                "properties": flatten_properties(row.get("properties")),
            }
        )

    data = {
        "results": results,
        "count": len(results),
        "has_more": bool(payload.get("has_more")),
    }
    if not results:
        return ToolResult(ok=True, content="No rows matched.", data=data)
    lines: list[str] = []
    for i, row in enumerate(results, 1):
        props = ", ".join(f"{k}={v}" for k, v in row["properties"].items())
        lines.append(f"{i}. [{row['id']}] {props}")
    suffix = (
        "\n\n(more rows available — narrow the filter or raise page_size)"
        if data["has_more"]
        else ""
    )
    return ToolResult(ok=True, content=cap("\n".join(lines) + suffix), data=data)


_DISPATCH = {
    "notion_search": _notion_search,
    "notion_get_page": _notion_get_page,
    "notion_create_page": _notion_create_page,
    "notion_append_blocks": _notion_append_blocks,
    "notion_query_database": _notion_query_database,
}


# ─── Integration object ──────────────────────────────────────────────────────────────


class NotionIntegration(Integration):
    name = "notion"
    label = "Notion"
    description = "Search, read, create, and update Notion pages and databases."
    setup_url = ""  # No OAuth — the integration secret is entered in the Tools UI.
    schemas = NOTION_SCHEMAS

    logo_url = "https://cdn.simpleicons.org/notion"
    connect_mode = "config"
    setup = NOTION_SETUP
    action_meta = NOTION_ACTION_META

    credentials_namespace = CREDENTIALS_NAMESPACE
    credentials_fields = [
        CredentialField(
            name="token",
            label="Internal integration secret (ntn_… / secret_…)",
            secret=True,
            placeholder="ntn_…",
        ),
    ]

    async def is_configured(self, session: AsyncSession) -> bool:
        creds = await get_credentials(session, CREDENTIALS_NAMESPACE)
        return bool(creds and creds.get("token"))

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult:
        fn = _DISPATCH.get(function_name)
        if fn is None:
            return ToolResult(
                ok=False, content=f"Unknown notion function: {function_name}", retryable=False
            )
        # `AppError`s propagate on purpose — `app.tools.registry.execute_tool` turns them
        # into a failed ToolResult carrying the right `retryable` flag.
        return await fn(args, session)


notion_integration = NotionIntegration()
