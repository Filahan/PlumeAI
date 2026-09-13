"""Tests for the structured `ToolResult.data` payloads of the pre-existing actions.

`data` is what `{{step.output.count}}`-style refs in an automation document read, so each
test asserts the exact shape — and that `content` (what the LLM sees) is unchanged in
spirit: still the human-readable rendering.

Google-backed actions are driven by monkeypatching `authed_fetch`; the builtin tools go
through `httpx.MockTransport` via a patched `httpx.AsyncClient`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations.calendar import calendar_integration
from app.integrations.drive import drive_integration
from app.integrations.gmail import gmail_integration
from app.tools import builtin
from app.tools.builtin import http_request, web_fetch


def _script(monkeypatch: pytest.MonkeyPatch, integration: Any, routes: dict[str, Any]) -> None:
    """Answer `authed_fetch(path)` from `routes`, matched by path prefix."""

    async def _authed_fetch(
        _session: Any,
        path: str,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        for prefix, payload in routes.items():
            if path.startswith(prefix):
                return httpx.Response(200, json=payload)
        raise AssertionError(f"unscripted path: {path}")

    monkeypatch.setattr(integration, "authed_fetch", _authed_fetch)


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    """Make every `httpx.AsyncClient(...)` in `app.tools.builtin` answer with `response`,
    and skip the SSRF DNS check (the URL under test is never really resolved)."""
    real_client = httpx.AsyncClient

    def _factory(*_args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(lambda _r: response), **kwargs)

    monkeypatch.setattr(builtin.httpx, "AsyncClient", _factory)

    async def _allow(url: str) -> str:
        return url

    monkeypatch.setattr(builtin, "assert_public_url", _allow)


# ─── gmail_search / gmail_get ────────────────────────────────────────────────────────


async def test_gmail_search_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(
        monkeypatch,
        gmail_integration,
        {
            "/users/me/messages/m1": {
                "threadId": "t1",
                "snippet": "the snippet",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "dana@acme.com"},
                        {"name": "Subject", "value": "Budget"},
                        {"name": "Date", "value": "Thu, 4 Jun 2026 10:00:00 +0200"},
                    ]
                },
            },
            "/users/me/messages": {"messages": [{"id": "m1"}]},
        },
    )
    result = await gmail_integration.execute("gmail_search", {"query": "is:unread"}, None)

    assert result.ok is True
    assert result.data == {
        "count": 1,
        "messages": [
            {
                "id": "m1",
                "thread_id": "t1",
                "from": "dana@acme.com",
                "subject": "Budget",
                "date": "Thu, 4 Jun 2026 10:00:00 +0200",
                "snippet": "the snippet",
            }
        ],
    }
    assert "[m1] Budget" in result.content  # content unchanged


async def test_gmail_search_no_match_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, gmail_integration, {"/users/me/messages": {}})
    result = await gmail_integration.execute("gmail_search", {"query": "nope"}, None)
    assert result.content == "No messages matched."
    assert result.data == {"count": 0, "messages": []}


async def test_gmail_get_data(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    body = base64.urlsafe_b64encode(b"Hello there.").decode().rstrip("=")
    _script(
        monkeypatch,
        gmail_integration,
        {
            "/users/me/messages/m1": {
                "id": "m1",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": body},
                    "headers": [
                        {"name": "From", "value": "dana@acme.com"},
                        {"name": "To", "value": "me@acme.com"},
                        {"name": "Subject", "value": "Budget"},
                        {"name": "Date", "value": "Thu, 4 Jun 2026 10:00:00 +0200"},
                    ],
                },
            }
        },
    )
    result = await gmail_integration.execute("gmail_get", {"id": "m1"}, None)

    assert result.data == {
        "id": "m1",
        "from": "dana@acme.com",
        "to": "me@acme.com",
        "subject": "Budget",
        "date": "Thu, 4 Jun 2026 10:00:00 +0200",
        "body": "Hello there.",
    }
    assert "Subject: Budget" in result.content
    assert "Labels: INBOX" in result.content  # content still carries the labels line


# ─── drive_search ────────────────────────────────────────────────────────────────────


async def test_drive_search_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(
        monkeypatch,
        drive_integration,
        {
            "/files": {
                "files": [
                    {
                        "id": "f1",
                        "name": "Budget.xlsx",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                        "modifiedTime": "2026-06-04T10:00:00Z",
                    }
                ]
            }
        },
    )
    result = await drive_integration.execute("drive_search", {"query": "name contains 'x'"}, None)

    assert result.data == {
        "count": 1,
        "files": [
            {
                "id": "f1",
                "name": "Budget.xlsx",
                "mime_type": "application/vnd.google-apps.spreadsheet",
                "modified_time": "2026-06-04T10:00:00Z",
            }
        ],
    }
    assert "[f1] Budget.xlsx" in result.content


# ─── calendar_list_events ────────────────────────────────────────────────────────────


async def test_calendar_list_events_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(
        monkeypatch,
        calendar_integration,
        {
            "/calendars/primary/events": {
                "items": [
                    {
                        "id": "e1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-06-04T09:00:00+02:00"},
                        "end": {"dateTime": "2026-06-04T09:15:00+02:00"},
                        "location": "Zoom",
                        "attendees": [{"email": "a@x.com"}, {"email": "b@x.com"}],
                        "htmlLink": "https://calendar.google.com/e1",
                    },
                    {"id": "e2", "start": {"date": "2026-06-05"}, "end": {"date": "2026-06-06"}},
                ]
            }
        },
    )
    result = await calendar_integration.execute("calendar_list_events", {}, None)

    assert result.data["count"] == 2
    assert result.data["events"][0] == {
        "id": "e1",
        "summary": "Standup",
        "start": "2026-06-04T09:00:00+02:00",
        "end": "2026-06-04T09:15:00+02:00",
        "location": "Zoom",
        "attendees": 2,
        "link": "https://calendar.google.com/e1",
    }
    assert result.data["events"][1] == {
        "id": "e2",
        "summary": "",
        "start": "2026-06-05",
        "end": "2026-06-06",
        "location": "",
        "attendees": 0,
        "link": "",
    }
    assert "[e1] Standup" in result.content


# ─── builtin http ────────────────────────────────────────────────────────────────────


async def test_http_data_parses_a_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(
        monkeypatch,
        httpx.Response(
            201,
            headers={"content-type": "application/json", "etag": "W/abc", "set-cookie": "s=1"},
            json={"id": 7, "nested": {"ok": True}},
        ),
    )
    result = await http_request({"method": "POST", "url": "https://api.example.com/things"})

    assert result.ok is True
    assert result.data["status"] == 201
    assert result.data["body"] == {"id": 7, "nested": {"ok": True}}
    # Only the useful headers travel; cookies never do.
    assert result.data["headers"] == {
        "content-type": "application/json",
        "content-length": "29",
        "etag": "W/abc",
    }
    assert result.content.startswith("HTTP 201 POST https://api.example.com/things")


async def test_http_data_falls_back_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(
        monkeypatch,
        httpx.Response(500, headers={"content-type": "text/plain"}, text="boom"),
    )
    result = await http_request({"method": "GET", "url": "https://api.example.com/x"})

    assert result.ok is False
    assert result.data == {
        "status": 500,
        "headers": {"content-type": "text/plain", "content-length": "4"},
        "body": "boom",
    }


async def test_http_data_keeps_text_for_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(
        monkeypatch,
        httpx.Response(200, headers={"content-type": "application/json"}, text="{not json"),
    )
    result = await http_request({"method": "GET", "url": "https://api.example.com/x"})
    assert result.data["body"] == "{not json"


# ─── builtin web_fetch ───────────────────────────────────────────────────────────────


async def test_web_fetch_data_includes_title_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><head><title>  Acme &amp; Co  </title></head>"
        "<body><script>ignore()</script><p>Hello there.</p></body></html>"
    )
    _mock_httpx(monkeypatch, httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await web_fetch({"url": "https://example.com/page"})

    assert result.ok is True
    assert result.data["url"] == "https://example.com/page"
    assert result.data["title"] == "Acme & Co"
    assert "Hello there." in result.data["text"]
    assert "ignore()" not in result.data["text"]
    assert result.content.startswith("HTTP 200 https://example.com/page")


async def test_web_fetch_data_without_a_title(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(
        monkeypatch,
        httpx.Response(200, headers={"content-type": "text/plain"}, text="just text"),
    )
    result = await web_fetch({"url": "https://example.com/raw.txt"})

    assert result.data == {"url": "https://example.com/raw.txt", "text": "just text"}
    assert "title" not in result.data
