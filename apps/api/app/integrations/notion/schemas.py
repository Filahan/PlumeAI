"""Notion catalog metadata: setup guide, per-action display metadata, and the OpenAI
function-calling schemas. Split out of `tools.py` so that module stays about behavior.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import ActionDisplayMeta

NOTION_SETUP: dict[str, Any] = {
    "intro": (
        "Notion uses an internal integration token. Create the integration once, copy its "
        "secret above, then share the pages it should reach."
    ),
    "steps": [
        {
            "title": "Create an internal integration",
            "description": (
                'New integration → give it a name (e.g. "PlumeAI") and pick your workspace. '
                "Copy the Internal Integration Secret into the Credentials section above."
            ),
            "link": {
                "label": "Open notion.so/my-integrations",
                "url": "https://www.notion.so/my-integrations",
            },
        },
        {
            "title": "Enable its content capabilities",
            "description": (
                "In the integration's Capabilities tab, keep Read content, Insert content "
                "and Update content enabled."
            ),
        },
        {
            "title": "Share each page or database with the integration",
            "description": (
                'Open the page in Notion → "…" menu → Connections → pick your integration. '
                "Sharing a parent page also shares everything nested under it."
            ),
        },
    ],
    "note": (
        "Pages you have not shared with the integration are invisible to the API — that is "
        "why a search can come back empty even though the token works."
    ),
}

NOTION_ACTION_META: dict[str, ActionDisplayMeta] = {
    "notion_search": ActionDisplayMeta(
        label="Search pages",
        output_description=(
            "Matching pages and databases with id, title, url, and last edited time."
        ),
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "number"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "object": {"type": "string"},
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "last_edited_time": {"type": "string"},
                        },
                    },
                },
            },
        },
    ),
    "notion_get_page": ActionDisplayMeta(
        label="Read a page",
        output_description="The page title, url, flattened properties, and its text content.",
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "properties": {"type": "object"},
                "content": {"type": "string"},
            },
        },
    ),
    "notion_create_page": ActionDisplayMeta(
        label="Create a page",
        output_description="The new page's id, title, and url.",
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    ),
    "notion_append_blocks": ActionDisplayMeta(
        label="Append to a page",
        output_description="How many blocks were appended.",
        output_schema={"type": "object", "properties": {"appended": {"type": "number"}}},
    ),
    "notion_query_database": ActionDisplayMeta(
        label="Query a database",
        output_description=(
            "Matching rows with id, url, and flattened properties, plus whether more pages exist."
        ),
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "number"},
                "has_more": {"type": "boolean"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "url": {"type": "string"},
                            "properties": {"type": "object"},
                        },
                    },
                },
            },
        },
    ),
}

NOTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "notion_search",
            "description": (
                "Search the Notion pages and databases shared with the integration. "
                "Returns id, title, url and last edited time. Call this first to turn a "
                "page name into an id. Pages not shared with the integration never appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search titles for."},
                    "filter": {
                        "type": "string",
                        "enum": ["page", "database"],
                        "description": "Restrict results to pages or to databases.",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max results to return (1-50, default 10).",
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
            "name": "notion_get_page",
            "description": (
                "Read one Notion page: its properties and the text of its blocks. Accepts a "
                "page id (dashed or plain 32-char form)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "string", "description": "Notion page id."}},
                "required": ["page_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notion_create_page",
            "description": (
                "Create a Notion page under a parent page or as a row in a database. "
                "`content` is markdown: # / ## / ### headings, - bullets, 1. numbered items, "
                "> quotes, ``` code fences, blank-line separated paragraphs. When "
                "parent_type is 'database', pass database column values in `properties` "
                "using Notion's property value shape."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {
                        "type": "string",
                        "description": "Id of the parent page, or of the database to add a row to.",
                    },
                    "parent_type": {
                        "type": "string",
                        "enum": ["page", "database"],
                        "description": "Whether parent_id is a page or a database (default page).",
                    },
                    "title": {"type": "string", "description": "Title of the new page."},
                    "content": {"type": "string", "description": "Page body as markdown."},
                    "properties": {
                        "type": "object",
                        "description": (
                            "Extra Notion property values, keyed by property name "
                            '(e.g. {"Status": {"select": {"name": "Done"}}}).'
                        ),
                    },
                },
                "required": ["parent_id", "title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notion_append_blocks",
            "description": (
                "Append markdown content to the end of an existing Notion page. Same "
                "markdown support as notion_create_page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Page (or block) id to append to.",
                    },
                    "content": {"type": "string", "description": "Markdown content to append."},
                },
                "required": ["page_id", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notion_query_database",
            "description": (
                "Query a Notion database and return its rows with flattened property values. "
                "`filter` and `sorts` take Notion's own filter/sort JSON shapes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {"type": "string", "description": "Notion database id."},
                    "filter": {
                        "type": "object",
                        "description": (
                            "Notion filter object, e.g. "
                            '{"property": "Status", "select": {"equals": "Done"}}.'
                        ),
                    },
                    "sorts": {
                        "type": "array",
                        "description": (
                            "Notion sort array, e.g. "
                            '[{"property": "Due", "direction": "ascending"}].'
                        ),
                        "items": {"type": "object"},
                    },
                    "page_size": {
                        "type": "number",
                        "description": "Max rows to return (1-100, default 25).",
                    },
                },
                "required": ["database_id"],
                "additionalProperties": False,
            },
        },
    },
]
