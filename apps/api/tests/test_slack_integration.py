"""Tests for the native Slack integration — no network.

Every Slack call goes through `app.integrations.slack.client._http_client`, so each test
swaps that factory for an `httpx.AsyncClient` backed by a `MockTransport` scripting the
Web API responses. Credentials are monkeypatched too, so nothing touches the database.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.base import get_session
from app.errors import ToolError, ToolNotConfigured
from app.integrations.registry import INTEGRATIONS
from app.integrations.slack import client as slack_client
from app.integrations.slack import slack_integration
from app.integrations.slack import tools as slack_tools
from app.main import app
from app.services import mcp_servers as mcp_service

FAKE_TOKEN = "xoxb-test"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get_credentials(_session: Any, _namespace: str) -> dict[str, str]:
        return {"bot_token": FAKE_TOKEN}

    monkeypatch.setattr(slack_client, "get_credentials", _get_credentials)


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    """Route every Slack HTTP call to `handler`. Returns the list of captured requests."""
    seen: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        slack_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_wrapped)),
    )
    return seen


def _method(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1]


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode())


def _ok(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, **payload})


def _err(code: str, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": False, "error": code, **extra})


def _channel(cid: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "is_private": False, **extra}


# ─── slack_list_channels ─────────────────────────────────────────────────────────────


async def test_list_channels_follows_pagination_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "channels": [
                _channel("C1", "general", num_members=12, topic={"value": "Everything"}),
            ],
            "response_metadata": {"next_cursor": "cur2"},
        },
        {"channels": [{"id": "C2", "name": "secret", "is_private": True}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert _method(request) == "conversations.list"
        form = _form(request)
        assert form["types"] == "public_channel,private_channel"
        assert form["exclude_archived"] == "true"
        return _ok(pages[0] if "cursor" not in form else pages[1])

    seen = _install(monkeypatch, handler)
    result = await slack_integration.execute("slack_list_channels", {"limit": 50}, None)

    assert len(seen) == 2  # both pages fetched
    assert result.ok is True
    assert result.data == {
        "count": 2,
        "channels": [
            {
                "id": "C1",
                "name": "general",
                "is_private": False,
                "num_members": 12,
                "topic": "Everything",
            },
            {"id": "C2", "name": "secret", "is_private": True},
        ],
    }
    assert "#general (public, 12 members) — Everything" in result.content
    assert "#secret (private)" in result.content


async def test_list_channels_types_public_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert _form(request)["types"] == "public_channel"
        return _ok({"channels": []})

    _install(monkeypatch, handler)
    result = await slack_integration.execute("slack_list_channels", {"types": "public"}, None)
    assert result.ok is True
    assert result.data == {"count": 0, "channels": []}
    assert "Invite it" in result.content


# ─── slack_send_message ──────────────────────────────────────────────────────────────


async def test_send_message_resolves_channel_name_and_returns_ts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        method = _method(request)
        if method == "conversations.list":
            return _ok({"channels": [_channel("C1", "general"), _channel("C2", "random")]})
        if method == "chat.postMessage":
            posted.update(_body(request))
            return _ok({"channel": "C1", "ts": "1712345678.000100"})
        if method == "chat.getPermalink":
            return _ok({"permalink": "https://acme.slack.com/archives/C1/p1712345678000100"})
        raise AssertionError(f"unexpected method {method}")

    _install(monkeypatch, handler)
    result = await slack_integration.execute(
        "slack_send_message",
        {"channel": "#general", "text": "hello", "thread_ts": "1712000000.000001"},
        None,
    )

    assert posted == {
        "channel": "C1",  # "#general" resolved via conversations.list
        "text": "hello",
        "thread_ts": "1712000000.000001",
    }
    assert result.ok is True
    assert result.data == {
        "channel": "C1",
        "ts": "1712345678.000100",
        "permalink": "https://acme.slack.com/archives/C1/p1712345678000100",
    }
    assert "Sent to #general" in result.content


async def test_send_message_accepts_raw_channel_id_without_a_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = _method(request)
        assert method != "conversations.list"  # an id needs no resolution
        if method == "chat.postMessage":
            return _ok({"channel": "C9", "ts": "1.2"})
        return _err("not_allowed")  # permalink lookup is best-effort

    _install(monkeypatch, handler)
    result = await slack_integration.execute(
        "slack_send_message", {"channel": "C9", "text": "hi"}, None
    )
    assert result.ok is True
    assert result.data == {"channel": "C9", "ts": "1.2"}  # no permalink, no failure


async def test_send_message_not_in_channel_tells_the_user_to_invite_the_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _method(request) == "conversations.list":
            return _ok({"channels": [_channel("C1", "general")]})
        return _err("not_in_channel")

    _install(monkeypatch, handler)
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute(
            "slack_send_message", {"channel": "#general", "text": "hello"}, None
        )

    assert "/invite" in exc.value.detail
    assert "#general" in exc.value.detail
    assert exc.value.extra == {"retryable": False}


async def test_send_message_unknown_channel_name_is_a_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda _r: _ok({"channels": [_channel("C1", "general")]}))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute(
            "slack_send_message", {"channel": "#nope", "text": "hello"}, None
        )
    assert "#nope" in exc.value.detail
    assert exc.value.extra == {"retryable": False}


async def test_send_message_requires_text() -> None:
    result = await slack_integration.execute("slack_send_message", {"channel": "C1"}, None)
    assert result.ok is False
    assert result.retryable is False


# ─── slack_read_messages ─────────────────────────────────────────────────────────────


async def test_read_messages_resolves_user_names_and_orders_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = {"U1": "dana", "U2": "sam"}
    history_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        method = _method(request)
        if method == "conversations.history":
            history_params.update(_form(request))
            return _ok(
                {
                    "messages": [  # Slack returns newest first
                        {"ts": "200.0", "user": "U2", "text": "second", "thread_ts": "200.0"},
                        {"ts": "100.0", "user": "U1", "text": "first"},
                    ]
                }
            )
        if method == "users.info":
            uid = _form(request)["user"]
            return _ok({"user": {"profile": {"display_name": users[uid]}}})
        raise AssertionError(f"unexpected method {method}")

    seen = _install(monkeypatch, handler)
    result = await slack_integration.execute(
        "slack_read_messages",
        {"channel": "C1", "limit": 5, "oldest": "2024-04-05T00:00:00Z"},
        None,
    )

    assert history_params["channel"] == "C1"
    assert history_params["limit"] == "5"
    assert history_params["oldest"] == "1712275200.000000"  # ISO → Slack ts
    assert result.data == {
        "count": 2,
        "messages": [
            {"ts": "100.0", "user": "U1", "text": "first", "user_name": "dana"},
            {
                "ts": "200.0",
                "user": "U2",
                "text": "second",
                "user_name": "sam",
                "thread_ts": "200.0",
            },
        ],
    }
    lines = result.content.splitlines()
    assert "dana: first" in lines[0]  # oldest first
    assert "sam: second" in lines[1]
    assert sum(1 for r in seen if _method(r) == "users.info") == 2  # one per distinct user


async def test_read_messages_survives_a_missing_users_read_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _method(request) == "conversations.history":
            return _ok({"messages": [{"ts": "100.0", "user": "U1", "text": "hi"}]})
        return _err("missing_scope", needed="users:read")

    _install(monkeypatch, handler)
    result = await slack_integration.execute("slack_read_messages", {"channel": "C1"}, None)

    assert result.ok is True
    assert result.data["messages"] == [{"ts": "100.0", "user": "U1", "text": "hi"}]
    assert "U1: hi" in result.content


async def test_read_messages_rejects_an_unparseable_oldest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda _r: _ok({"messages": []}))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute(
            "slack_read_messages", {"channel": "C1", "oldest": "last tuesday"}, None
        )
    assert exc.value.extra == {"retryable": False}


# ─── error mapping ───────────────────────────────────────────────────────────────────


async def test_ok_false_invalid_auth_is_a_permanent_human_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda _r: _err("invalid_auth"))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute("slack_list_channels", {}, None)
    assert "bot token" in exc.value.detail.lower()
    assert exc.value.extra == {"retryable": False}


async def test_missing_scope_names_the_missing_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: _err("missing_scope", needed="channels:read"))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute("slack_list_channels", {}, None)
    assert "channels:read" in exc.value.detail
    assert exc.value.extra == {"retryable": False}


async def test_unknown_ok_false_code_still_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: _err("weird_new_error"))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute("slack_list_channels", {}, None)
    assert "weird_new_error" in exc.value.detail


async def test_http_429_is_retryable_and_mentions_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        lambda _r: httpx.Response(429, headers={"retry-after": "42"}, json={"ok": False}),
    )
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute("slack_list_channels", {}, None)
    assert "42" in exc.value.detail
    assert exc.value.extra.get("retryable", True) is True


async def test_ratelimited_ok_false_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: _err("ratelimited"))
    with pytest.raises(ToolError) as exc:
        await slack_integration.execute("slack_list_channels", {}, None)
    assert exc.value.extra.get("retryable", True) is True


async def test_missing_bot_token_raises_tool_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_credentials(_session: Any, _namespace: str) -> None:
        return None

    monkeypatch.setattr(slack_client, "get_credentials", _no_credentials)
    _install(monkeypatch, lambda _r: _ok({"channels": []}))
    with pytest.raises(ToolNotConfigured):
        await slack_integration.execute("slack_list_channels", {}, None)


async def test_unknown_function_name() -> None:
    result = await slack_integration.execute("slack_nope", {}, None)
    assert result.ok is False
    assert result.retryable is False


# ─── catalog surface ─────────────────────────────────────────────────────────────────


def test_describe_actions_shape() -> None:
    actions = slack_integration.describe_actions()
    assert {a.name for a in actions} == {
        "slack_list_channels",
        "slack_send_message",
        "slack_read_messages",
    }
    for action in actions:
        assert action.integration == "slack"
        assert action.label and not action.label.startswith("Slack ")  # real label, not humanized
        assert action.description
        assert action.input_schema["type"] == "object"
        assert action.output_description
        assert action.output_schema is not None

    send = next(a for a in actions if a.name == "slack_send_message")
    assert send.input_schema["required"] == ["channel", "text"]


async def test_is_configured_reads_the_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _creds(_session: Any, _namespace: str) -> dict[str, str]:
        return {"bot_token": FAKE_TOKEN}

    monkeypatch.setattr(slack_tools, "get_credentials", _creds)
    assert await slack_integration.is_configured(None) is True

    async def _empty(_session: Any, _namespace: str) -> dict[str, str]:
        return {}

    monkeypatch.setattr(slack_tools, "get_credentials", _empty)
    assert await slack_integration.is_configured(None) is False


async def _dummy_session() -> AsyncIterator[None]:
    yield None


async def test_get_tools_lists_slack_as_a_config_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_connected(_session: Any) -> bool:
        return False

    for integ in INTEGRATIONS:
        monkeypatch.setattr(integ, "is_configured", _not_connected)

    # The catalog also lists MCP servers from the DB; this file stays DB-free.
    async def _no_mcp_servers(_session: Any) -> list[Any]:
        return []

    monkeypatch.setattr(mcp_service, "list_servers", _no_mcp_servers)

    app.dependency_overrides[get_session] = _dummy_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/tools")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    slack = next(i for i in resp.json()["integrations"] if i["name"] == "slack")
    assert slack["connected"] is False
    assert slack["connectMode"] == "config"
    assert slack["logoUrl"] == "https://cdn.simpleicons.org/slack"
    assert slack["credentialsFields"] == [
        {
            "name": "bot_token",
            "label": "Bot token (xoxb-…)",
            "secret": True,
            "placeholder": "xoxb-…",
        }
    ]
    assert slack["setup"]["intro"]
    assert len(slack["setup"]["steps"]) == 4
    assert {a["name"] for a in slack["actions"]} == {
        "slack_list_channels",
        "slack_send_message",
        "slack_read_messages",
    }
