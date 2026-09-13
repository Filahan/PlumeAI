"""Tests for the native Notion integration — no network.

Notion calls go through `app.integrations.notion.client._http_client`, which each test
swaps for an `httpx.AsyncClient` on a `MockTransport`. The markdown → blocks converter
is tested directly, since it is the part with real logic.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.base import get_session
from app.errors import ToolError, ToolNotConfigured
from app.integrations.notion import client as notion_client
from app.integrations.notion import notion_integration
from app.integrations.notion import tools as notion_tools
from app.integrations.notion.blocks import (
    MAX_BLOCKS_PER_REQUEST,
    MAX_TEXT_CHARS,
    blocks_to_text,
    markdown_to_blocks,
)
from app.integrations.notion.client import flatten_properties
from app.integrations.registry import INTEGRATIONS
from app.main import app

FAKE_TOKEN = "ntn_test"  # pragma: allowlist secret

# Notion ids are 32 hex characters; anything else is rejected before the request is built.
PAGE_ID = "a" * 32
PARENT_ID = "b" * 32
DATABASE_ID = "c" * 32


@pytest.fixture(autouse=True)
def _configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get_credentials(_session: Any, _namespace: str) -> dict[str, str]:
        return {"token": FAKE_TOKEN}

    monkeypatch.setattr(notion_client, "get_credentials", _get_credentials)


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        notion_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_wrapped)),
    )
    return seen


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode())


def _rich(text: str) -> list[dict[str, Any]]:
    return [{"plain_text": text}]


def _text_of(block: dict[str, Any]) -> str:
    payload = block[block["type"]]
    return "".join(item["text"]["content"] for item in payload["rich_text"])


# ─── notion_search ───────────────────────────────────────────────────────────────────


async def test_search_extracts_page_and_database_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/search"
        assert request.headers["Notion-Version"] == "2022-06-28"
        assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
        sent.update(_body(request))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "object": "page",
                        "id": "page-1",
                        "url": "https://notion.so/page-1",
                        "last_edited_time": "2026-06-04T10:00:00.000Z",
                        "properties": {
                            "Tags": {"type": "multi_select", "multi_select": []},
                            "Name": {"type": "title", "title": _rich("Roadmap")},
                        },
                    },
                    {
                        "object": "database",
                        "id": "db-1",
                        "url": "https://notion.so/db-1",
                        "last_edited_time": "2026-06-03T10:00:00.000Z",
                        "title": _rich("Tasks"),
                    },
                    {
                        "object": "page",
                        "id": "page-2",
                        "url": "",
                        "last_edited_time": "",
                        "properties": {},
                    },
                ]
            },
        )

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_search", {"query": "road", "filter": "page", "limit": 5}, None
    )

    assert sent == {
        "query": "road",
        "page_size": 5,
        "filter": {"property": "object", "value": "page"},
    }
    assert result.ok is True
    assert result.data["count"] == 3
    assert [r["title"] for r in result.data["results"]] == ["Roadmap", "Tasks", "(untitled)"]
    assert result.data["results"][0] == {
        "id": "page-1",
        "object": "page",
        "title": "Roadmap",
        "url": "https://notion.so/page-1",
        "last_edited_time": "2026-06-04T10:00:00.000Z",
    }
    assert "Roadmap" in result.content


async def test_search_empty_mentions_sharing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(200, json={"results": []}))
    result = await notion_integration.execute("notion_search", {"query": "nope"}, None)
    assert result.ok is True
    assert result.data == {"count": 0, "results": [], "has_more": False}
    assert "Connections" in result.content


# ─── notion_get_page ─────────────────────────────────────────────────────────────────


async def test_get_page_reads_properties_and_paginates_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {
            "results": [
                {"type": "heading_1", "heading_1": {"rich_text": _rich("Intro")}},
                {"type": "paragraph", "paragraph": {"rich_text": _rich("Hello there.")}},
            ],
            "has_more": True,
            "next_cursor": "cur2",
        },
        {
            "results": [
                {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich("one")}},
                {"type": "to_do", "to_do": {"rich_text": _rich("ship it"), "checked": True}},
                {"type": "code", "code": {"rich_text": _rich("print(1)"), "language": "python"}},
                {"type": "divider", "divider": {}},
                {"type": "unsupported_thing", "unsupported_thing": {}},
            ],
            "has_more": False,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1/pages/{PAGE_ID}":
            return httpx.Response(
                200,
                json={
                    "object": "page",
                    "id": PAGE_ID,
                    "url": "https://notion.so/abc",
                    "properties": {
                        "Name": {"type": "title", "title": _rich("Design doc")},
                        "Status": {"type": "select", "select": {"name": "Draft"}},
                    },
                },
            )
        assert path == f"/v1/blocks/{PAGE_ID}/children"
        cursor = request.url.params.get("start_cursor")
        return httpx.Response(200, json=pages[0] if cursor is None else pages[1])

    _install(monkeypatch, handler)
    result = await notion_integration.execute("notion_get_page", {"page_id": PAGE_ID}, None)

    assert result.ok is True
    assert result.data["id"] == PAGE_ID
    assert result.data["title"] == "Design doc"
    assert result.data["url"] == "https://notion.so/abc"
    assert result.data["properties"] == {"Name": "Design doc", "Status": "Draft"}
    assert result.data["content"] == (
        "# Intro\nHello there.\n- one\n- [x] ship it\n```python\nprint(1)\n```\n---"
    )
    assert result.content.startswith("# Design doc")
    assert "Status: Draft" in result.content
    assert "Name: Design doc" not in result.content  # the title is not repeated


async def test_get_page_reports_truncation_and_nested_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page longer than MAX_READ_BLOCKS says so, and a block with children is marked
    rather than silently flattened."""
    page_of_100 = {
        "results": [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": _rich(f"para {i}")},
                "has_children": i == 0,
            }
            for i in range(100)
        ],
        "has_more": True,
        "next_cursor": "more",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{PAGE_ID}":
            return httpx.Response(200, json={"object": "page", "id": PAGE_ID, "properties": {}})
        return httpx.Response(200, json=page_of_100)

    _install(monkeypatch, handler)
    result = await notion_integration.execute("notion_get_page", {"page_id": PAGE_ID}, None)

    assert result.data["truncated"] is True
    assert "…[truncated at 200 blocks]" in result.data["content"]
    assert "para 0 (has nested content)" in result.data["content"]
    assert "para 1 (has nested content)" not in result.data["content"]


async def test_get_page_is_not_truncated_when_the_page_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{PAGE_ID}":
            return httpx.Response(200, json={"object": "page", "id": PAGE_ID, "properties": {}})
        return httpx.Response(
            200,
            json={
                "results": [{"type": "paragraph", "paragraph": {"rich_text": _rich("hi")}}],
                "has_more": False,
            },
        )

    _install(monkeypatch, handler)
    result = await notion_integration.execute("notion_get_page", {"page_id": PAGE_ID}, None)
    assert result.data["truncated"] is False
    assert result.data["content"] == "hi"


async def test_get_page_accepts_a_pasted_notion_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/pages/"):
            assert request.url.path == f"/v1/pages/{PAGE_ID}"
            return httpx.Response(200, json={"object": "page", "id": PAGE_ID, "properties": {}})
        return httpx.Response(200, json={"results": [], "has_more": False})

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_get_page",
        {"page_id": f"https://www.notion.so/acme/Design-doc-{PAGE_ID}"},
        None,
    )
    assert result.ok is True


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../v1/users",
        f"{PAGE_ID}?x=1&y=2",  # a query string is not part of an id
        "abc",
        "",
        "not-an-id-at-all",
    ],
)
async def test_ids_that_are_not_notion_ids_are_rejected_before_any_request(
    monkeypatch: pytest.MonkeyPatch, bad_id: str
) -> None:
    """The id goes straight into the URL path, so anything unparseable must be refused
    here — never interpolated and sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request should be made, got {request.url}")

    _install(monkeypatch, handler)
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute("notion_get_page", {"page_id": bad_id}, None)
    assert exc.value.extra == {"retryable": False}


async def test_a_dashed_id_with_a_query_string_is_still_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notion's own share links append ?pvs=4 — the id in front of it is still valid."""
    dashed = f"{PAGE_ID[:8]}-{PAGE_ID[8:12]}-{PAGE_ID[12:16]}-{PAGE_ID[16:20]}-{PAGE_ID[20:]}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/pages/{PAGE_ID}":
            return httpx.Response(200, json={"object": "page", "id": PAGE_ID, "properties": {}})
        return httpx.Response(200, json={"results": [], "has_more": False})

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_get_page", {"page_id": f"https://notion.so/acme/{dashed}?pvs=4"}, None
    )
    assert result.ok is True


# ─── markdown → blocks ───────────────────────────────────────────────────────────────


def test_markdown_to_blocks_covers_every_supported_construct() -> None:
    md = (
        "# Title\n"
        "## Sub\n"
        "### Deep\n"
        "\n"
        "First paragraph line\nsame paragraph.\n"
        "\n"
        "- bullet one\n"
        "* bullet two\n"
        "- [ ] todo open\n"
        "- [x] todo done\n"
        "1. first\n"
        "2. second\n"
        "> a quote\n"
        "---\n"
        "```python\nprint('hi')\nprint('bye')\n```\n"
        "\n"
        "Trailing paragraph."
    )
    blocks = markdown_to_blocks(md)
    kinds = [b["type"] for b in blocks]
    assert kinds == [
        "heading_1",
        "heading_2",
        "heading_3",
        "paragraph",
        "bulleted_list_item",
        "bulleted_list_item",
        "to_do",
        "to_do",
        "numbered_list_item",
        "numbered_list_item",
        "quote",
        "divider",
        "code",
        "paragraph",
    ]
    assert _text_of(blocks[0]) == "Title"
    assert _text_of(blocks[3]) == "First paragraph line\nsame paragraph."
    assert blocks[6]["to_do"]["checked"] is False
    assert blocks[7]["to_do"]["checked"] is True
    assert _text_of(blocks[9]) == "second"
    assert blocks[12]["code"]["language"] == "python"
    assert _text_of(blocks[12]) == "print('hi')\nprint('bye')"
    assert _text_of(blocks[13]) == "Trailing paragraph."
    assert all(b["object"] == "block" for b in blocks)


def test_markdown_to_blocks_chunks_long_paragraphs_at_2000_chars() -> None:
    words = " ".join("word" for _ in range(1200))  # ~6000 chars
    blocks = markdown_to_blocks(words)
    assert len(blocks) == 3
    assert all(b["type"] == "paragraph" for b in blocks)
    assert all(len(_text_of(b)) <= MAX_TEXT_CHARS for b in blocks)
    assert "".join(_text_of(b) for b in blocks).replace(" ", "") == words.replace(" ", "")


def test_markdown_to_blocks_hard_splits_text_with_no_space_boundary() -> None:
    blocks = markdown_to_blocks("x" * (MAX_TEXT_CHARS + 10))
    assert len(blocks) == 2
    assert len(_text_of(blocks[0])) == MAX_TEXT_CHARS
    assert len(_text_of(blocks[1])) == 10


def test_markdown_to_blocks_language_aliases_and_unclosed_fence() -> None:
    assert markdown_to_blocks("```ts\nconst a = 1\n```")[0]["code"]["language"] == "typescript"
    assert markdown_to_blocks("```\nplain\n```")[0]["code"]["language"] == "plain text"
    unclosed = markdown_to_blocks("```\nstill code")
    assert len(unclosed) == 1
    assert _text_of(unclosed[0]) == "still code"


def test_markdown_to_blocks_chunks_a_long_code_fence_without_losing_anything() -> None:
    code = "\n".join(f"line {i} " + "x" * 60 for i in range(200))  # ~14k chars
    blocks = markdown_to_blocks(f"```python\n{code}\n```")

    assert len(blocks) == 1  # still ONE code block…
    rich = blocks[0]["code"]["rich_text"]
    assert len(rich) > 1  # …split across several rich_text items
    assert all(len(item["text"]["content"]) <= MAX_TEXT_CHARS for item in rich)
    assert "".join(item["text"]["content"] for item in rich) == code
    assert all(item["text"]["content"].endswith("\n") for item in rich[:-1])  # cut on newlines


def test_blocks_to_text_round_trips_the_common_constructs() -> None:
    md = "# Title\n- one\n1. two\n> quote\n---"
    blocks = markdown_to_blocks(md)
    rendered = [
        {
            "type": b["type"],
            b["type"]: {} if b["type"] == "divider" else {"rich_text": _rich(_text_of(b))},
        }
        for b in blocks
    ]
    assert blocks_to_text(rendered) == "# Title\n- one\n1. two\n> quote\n---"


# ─── notion_create_page / notion_append_blocks ───────────────────────────────────────


async def test_create_page_under_a_page_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/pages"
        sent.update(_body(request))
        return httpx.Response(200, json={"id": "new-1", "url": "https://notion.so/new-1"})

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_create_page",
        {"parent_id": PARENT_ID, "title": "Weekly notes", "content": "# Hi\n- a"},
        None,
    )

    assert sent["parent"] == {"page_id": PARENT_ID}
    assert sent["properties"]["title"]["title"][0]["text"]["content"] == "Weekly notes"
    assert [b["type"] for b in sent["children"]] == ["heading_1", "bulleted_list_item"]
    assert result.data == {"id": "new-1", "url": "https://notion.so/new-1", "title": "Weekly notes"}


async def test_create_page_in_a_database_looks_up_the_title_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/databases/{DATABASE_ID}":
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "Status": {"type": "select"},
                        "Task name": {"type": "title"},
                    }
                },
            )
        sent.update(_body(request))
        return httpx.Response(200, json={"id": "row-1", "url": "https://notion.so/row-1"})

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_create_page",
        {
            "parent_id": DATABASE_ID,
            "parent_type": "database",
            "title": "Fix the build",
            "properties": {"Status": {"select": {"name": "Todo"}}},
        },
        None,
    )

    assert sent["parent"] == {"database_id": DATABASE_ID}
    assert sent["properties"]["Task name"]["title"][0]["text"]["content"] == "Fix the build"
    assert sent["properties"]["Status"] == {"select": {"name": "Todo"}}
    assert "children" not in sent  # no content given
    assert result.data["id"] == "row-1"


async def test_create_page_appends_blocks_beyond_the_100_block_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/pages":
            assert len(_body(request)["children"]) == MAX_BLOCKS_PER_REQUEST
            return httpx.Response(200, json={"id": PAGE_ID, "url": "u"})
        assert request.method == "PATCH"
        assert request.url.path == f"/v1/blocks/{PAGE_ID}/children"
        batches.append(len(_body(request)["children"]))
        return httpx.Response(200, json={"results": []})

    _install(monkeypatch, handler)
    content = "\n\n".join(f"para {i}" for i in range(250))
    result = await notion_integration.execute(
        "notion_create_page", {"parent_id": PARENT_ID, "title": "Big", "content": content}, None
    )

    assert batches == [100, 50]  # 250 blocks → 100 inline + 100 + 50 appended
    assert result.ok is True
    assert "250 blocks" in result.content


async def test_append_blocks_batches_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        batches.append(len(_body(request)["children"]))
        return httpx.Response(200, json={"results": []})

    _install(monkeypatch, handler)
    content = "\n\n".join(f"para {i}" for i in range(130))
    result = await notion_integration.execute(
        "notion_append_blocks", {"page_id": PAGE_ID, "content": content}, None
    )

    assert batches == [100, 30]
    assert result.data == {"appended": 130}


async def test_a_partial_append_is_reported_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notion has no transaction across batches: once 100 blocks have landed, replaying
    the step would duplicate them, so the failure must be permanent and explicit."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(500, json={"message": "boom"})

    _install(monkeypatch, handler)
    content = "\n\n".join(f"para {i}" for i in range(130))
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute(
            "notion_append_blocks", {"page_id": PAGE_ID, "content": content}, None
        )

    assert "100 of 130" in exc.value.detail
    assert "duplicate" in exc.value.detail
    assert exc.value.extra == {"retryable": False}


async def test_a_failure_on_the_first_batch_keeps_the_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was written, so this is the ordinary (retryable) upstream failure."""
    _install(monkeypatch, lambda _r: httpx.Response(503, json={"message": "unavailable"}))
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute(
            "notion_append_blocks", {"page_id": PAGE_ID, "content": "just one para"}, None
        )
    assert "Partial write" not in exc.value.detail
    assert exc.value.extra.get("retryable", True) is True


async def test_a_failed_overflow_append_names_the_page_it_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/pages":
            return httpx.Response(200, json={"id": PAGE_ID, "url": "https://notion.so/x"})
        return httpx.Response(500, json={"message": "boom"})

    _install(monkeypatch, handler)
    content = "\n\n".join(f"para {i}" for i in range(150))
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute(
            "notion_create_page", {"parent_id": PARENT_ID, "title": "Big", "content": content},
            None,
        )

    assert PAGE_ID in exc.value.detail  # the page exists — do not create it again
    assert "https://notion.so/x" in exc.value.detail
    assert exc.value.extra == {"retryable": False}


async def test_the_title_argument_wins_over_a_title_in_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(_body(request))
        return httpx.Response(200, json={"id": PAGE_ID, "url": "u"})

    _install(monkeypatch, handler)
    await notion_integration.execute(
        "notion_create_page",
        {
            "parent_id": PARENT_ID,
            "title": "Real title",
            "properties": {"title": {"title": [{"text": {"content": "Sneaky"}}]}},
        },
        None,
    )
    assert sent["properties"]["title"]["title"][0]["text"]["content"] == "Real title"


async def test_append_blocks_requires_content() -> None:
    result = await notion_integration.execute(
        "notion_append_blocks", {"page_id": PAGE_ID, "content": "   "}, None
    )
    assert result.ok is False
    assert result.retryable is False


# ─── notion_query_database ───────────────────────────────────────────────────────────


def test_flatten_properties_handles_every_supported_type() -> None:
    props = {
        "Name": {"type": "title", "title": _rich("Fix the build")},
        "Notes": {"type": "rich_text", "rich_text": _rich("flaky test")},
        "Points": {"type": "number", "number": 3},
        "Stage": {"type": "select", "select": {"name": "Doing"}},
        "Status": {"type": "status", "status": {"name": "In progress"}},
        "Tags": {"type": "multi_select", "multi_select": [{"name": "bug"}, {"name": "ci"}]},
        "Window": {"type": "date", "date": {"start": "2026-06-01", "end": "2026-06-04"}},
        "Due": {"type": "date", "date": {"start": "2026-06-01"}},
        "Done": {"type": "checkbox", "checkbox": False},
        "Link": {"type": "url", "url": "https://example.com"},
        "Email": {"type": "email", "email": "dana@acme.com"},
        "Owner": {"type": "people", "people": [{"name": "Dana"}, {"id": "u-2"}]},
        "Empty text": {"type": "rich_text", "rich_text": []},
        "No option": {"type": "select", "select": None},
        "Unknown": {"type": "relation", "relation": [{"id": "x"}]},
    }
    assert flatten_properties(props) == {
        "Name": "Fix the build",
        "Notes": "flaky test",
        "Points": 3,
        "Stage": "Doing",
        "Status": "In progress",
        "Tags": ["bug", "ci"],
        "Window": "2026-06-01 → 2026-06-04",
        "Due": "2026-06-01",
        "Done": False,  # a False checkbox is a real value, not a missing one
        "Link": "https://example.com",
        "Email": "dana@acme.com",
        "Owner": ["Dana", "u-2"],
    }


async def test_query_database_flattens_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/databases/{DATABASE_ID}/query"
        sent.update(_body(request))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "row-1",
                        "url": "https://notion.so/row-1",
                        "properties": {
                            "Name": {"type": "title", "title": _rich("Fix the build")},
                            "Points": {"type": "number", "number": 3},
                        },
                    }
                ],
                "has_more": True,
            },
        )

    _install(monkeypatch, handler)
    result = await notion_integration.execute(
        "notion_query_database",
        {
            "database_id": DATABASE_ID,
            "filter": {"property": "Status", "select": {"equals": "Doing"}},
            "sorts": [{"property": "Due", "direction": "ascending"}],
            "page_size": 500,  # clamped to 100
        },
        None,
    )

    assert sent == {
        "page_size": 100,
        "filter": {"property": "Status", "select": {"equals": "Doing"}},
        "sorts": [{"property": "Due", "direction": "ascending"}],
    }
    assert result.data == {
        "count": 1,
        "has_more": True,
        "results": [
            {
                "id": "row-1",
                "url": "https://notion.so/row-1",
                "properties": {"Name": "Fix the build", "Points": 3},
            }
        ],
    }
    assert "more rows available" in result.content


async def test_query_database_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(200, json={"results": [], "has_more": False}))
    result = await notion_integration.execute(
        "notion_query_database", {"database_id": DATABASE_ID}, None
    )
    assert result.data == {"count": 0, "has_more": False, "results": []}


# ─── error mapping ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "needle", "retryable"),
    [
        (401, "rejected the token", False),
        (404, "not shared with the integration", False),
        (429, "Retry after 7s", True),
        (403, "capabilities", False),
        (400, "body.parent.page_id should be", False),
        (500, "HTTP 500", True),
    ],
)
async def test_error_status_mapping(
    monkeypatch: pytest.MonkeyPatch, status: int, needle: str, retryable: bool
) -> None:
    _install(
        monkeypatch,
        lambda _r: httpx.Response(
            status,
            headers={"retry-after": "7"},
            json={"code": "validation_error", "message": "body.parent.page_id should be a uuid"},
        ),
    )
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute("notion_search", {"query": "x"}, None)
    assert needle in exc.value.detail
    assert exc.value.extra.get("retryable", True) is retryable


async def test_search_surfaces_has_more(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        lambda _r: httpx.Response(
            200,
            json={
                "results": [
                    {
                        "object": "page",
                        "id": PAGE_ID,
                        "properties": {},
                        "url": "",
                        "last_edited_time": "",
                    }
                ],
                "has_more": True,
            },
        ),
    )
    result = await notion_integration.execute("notion_search", {"query": "x"}, None)
    assert result.data["has_more"] is True
    assert "more matches exist" in result.content


async def test_404_points_at_notion_query_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(404, json={"message": "not found"}))
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute("notion_get_page", {"page_id": PAGE_ID}, None)
    assert "notion_query_database" in exc.value.detail


async def test_429_carries_retry_after_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        lambda _r: httpx.Response(429, headers={"retry-after": "9"}, json={"message": "slow down"}),
    )
    with pytest.raises(ToolError) as exc:
        await notion_integration.execute("notion_search", {"query": "x"}, None)
    assert exc.value.extra["retry_after"] == 9
    assert exc.value.extra.get("retryable", True) is True


async def test_missing_token_raises_tool_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_credentials(_session: Any, _namespace: str) -> None:
        return None

    monkeypatch.setattr(notion_client, "get_credentials", _no_credentials)
    _install(monkeypatch, lambda _r: httpx.Response(200, json={"results": []}))
    with pytest.raises(ToolNotConfigured):
        await notion_integration.execute("notion_search", {"query": "x"}, None)


async def test_unknown_function_name() -> None:
    result = await notion_integration.execute("notion_nope", {}, None)
    assert result.ok is False
    assert result.retryable is False


# ─── catalog surface ─────────────────────────────────────────────────────────────────


def test_describe_actions_shape() -> None:
    actions = notion_integration.describe_actions()
    assert {a.name for a in actions} == {
        "notion_search",
        "notion_get_page",
        "notion_create_page",
        "notion_append_blocks",
        "notion_query_database",
    }
    for action in actions:
        assert action.integration == "notion"
        assert action.label
        assert action.description
        assert action.input_schema["type"] == "object"
        assert action.output_description
        assert action.output_schema is not None

    create = next(a for a in actions if a.name == "notion_create_page")
    assert create.input_schema["required"] == ["parent_id", "title"]


async def test_is_configured_reads_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _creds(_session: Any, _namespace: str) -> dict[str, str]:
        return {"token": FAKE_TOKEN}

    monkeypatch.setattr(notion_tools, "get_credentials", _creds)
    assert await notion_integration.is_configured(None) is True

    async def _empty(_session: Any, _namespace: str) -> dict[str, str]:
        return {}

    monkeypatch.setattr(notion_tools, "get_credentials", _empty)
    assert await notion_integration.is_configured(None) is False


async def _dummy_session() -> AsyncIterator[None]:
    yield None


async def test_get_tools_lists_notion_as_a_config_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_connected(_session: Any) -> bool:
        return False

    for integ in INTEGRATIONS:
        monkeypatch.setattr(integ, "is_configured", _not_connected)

    app.dependency_overrides[get_session] = _dummy_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/tools")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    names = {i["name"] for i in resp.json()["integrations"]}
    assert {"slack", "notion"} <= names

    notion = next(i for i in resp.json()["integrations"] if i["name"] == "notion")
    assert notion["connected"] is False
    assert notion["connectMode"] == "config"
    assert notion["logoUrl"] == "https://cdn.simpleicons.org/notion"
    assert notion["credentialsFields"] == [
        {
            "name": "token",
            "label": "Internal integration secret (ntn_… / secret_…)",
            "secret": True,
            "placeholder": "ntn_…",
        }
    ]
    assert len(notion["setup"]["steps"]) == 3
    assert len(notion["actions"]) == 5
