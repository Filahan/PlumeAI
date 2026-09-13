"""Tests for the tool/integration catalog: `describe_actions()`, `Catalog`, and `GET /tools`.

No test in this file touches the database — DB-backed calls (`is_configured`, the
`get_session` FastAPI dependency) are monkeypatched / overridden.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.base import get_session
from app.integrations.gmail import gmail_integration
from app.integrations.registry import INTEGRATIONS
from app.main import app
from app.services.catalog import Catalog, CatalogIntegration
from app.tools.builtin import BUILTIN_SCHEMAS, describe_builtin_actions


# ─── Integration.describe_actions() ────────────────────────────────────────────────────


def test_gmail_describe_actions_derives_name_label_input_schema_from_schemas() -> None:
    actions = gmail_integration.describe_actions()

    schema_names = {s["function"]["name"] for s in gmail_integration.schemas}
    assert {a["name"] for a in actions} == schema_names

    search_schema = next(
        s for s in gmail_integration.schemas if s["function"]["name"] == "gmail_search"
    )
    search_action = next(a for a in actions if a["name"] == "gmail_search")

    assert search_action["integration"] == "gmail"
    assert search_action["label"] == "Search emails"  # from GMAIL_ACTION_META
    assert search_action["description"] == search_schema["function"]["description"]
    assert search_action["input_schema"] == search_schema["function"]["parameters"]
    assert search_action["output_description"]  # non-empty, from ActionMeta
    assert search_action["output_schema"] is None


# ─── builtin action descriptions ───────────────────────────────────────────────────────


def test_describe_builtin_actions() -> None:
    actions = describe_builtin_actions()

    assert {a["name"] for a in actions} == {s["function"]["name"] for s in BUILTIN_SCHEMAS}
    for action in actions:
        assert action["integration"] == "builtin"
        assert action["label"]
        assert isinstance(action["input_schema"], dict)


# ─── Catalog.find_action / is_connected ────────────────────────────────────────────────


def _make_catalog(*, gmail_connected: bool) -> Catalog:
    gmail = CatalogIntegration(
        name="gmail",
        label="Gmail",
        description="Read, send, label, and trash Gmail messages.",
        logo_url="https://cdn.simpleicons.org/gmail",
        connect_mode="oauth",
        setup_url="/api/tools/gmail/oauth/start",
        credentials_namespace="google",
        credentials_fields=[],
        setup={},
        connected=gmail_connected,
        actions=gmail_integration.describe_actions(),
    )
    return Catalog(integrations=[gmail], builtin_actions=describe_builtin_actions())


def test_catalog_find_action() -> None:
    catalog = _make_catalog(gmail_connected=True)

    found = catalog.find_action("gmail_search")
    assert found is not None
    assert found.name == "gmail_search"
    assert found.integration == "gmail"
    assert found.label == "Search emails"
    assert isinstance(found.input_schema, dict)

    builtin_found = catalog.find_action("web_search")
    assert builtin_found is not None
    assert builtin_found.integration == "builtin"

    assert catalog.find_action("does_not_exist") is None


def test_catalog_is_connected() -> None:
    catalog = _make_catalog(gmail_connected=True)

    assert catalog.is_connected("gmail") is True
    assert catalog.is_connected("builtin") is True  # builtin is always "connected"
    assert catalog.is_connected("discord") is False  # not in this catalog at all

    disconnected = _make_catalog(gmail_connected=False)
    assert disconnected.is_connected("gmail") is False


# ─── GET /tools ─────────────────────────────────────────────────────────────────────────


async def _dummy_session() -> AsyncIterator[None]:
    yield None


async def test_get_tools_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full catalog, camelCase JSON, live connection status — no DB access."""

    async def _connected(_session: Any) -> bool:
        return True

    async def _not_connected(_session: Any) -> bool:
        return False

    for integ in INTEGRATIONS:
        monkeypatch.setattr(
            integ, "is_configured", _connected if integ.name == "gmail" else _not_connected
        )

    app.dependency_overrides[get_session] = _dummy_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/tools")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    body = resp.json()

    assert {i["name"] for i in body["integrations"]} == {"gmail", "drive", "calendar", "discord"}

    gmail = next(i for i in body["integrations"] if i["name"] == "gmail")
    assert gmail["connected"] is True
    assert gmail["connectMode"] == "oauth"
    assert gmail["logoUrl"] == "https://cdn.simpleicons.org/gmail"
    assert {a["name"] for a in gmail["actions"]} >= {"gmail_search", "gmail_send"}
    assert gmail["setup"]["intro"]

    drive = next(i for i in body["integrations"] if i["name"] == "drive")
    assert drive["connected"] is False

    discord = next(i for i in body["integrations"] if i["name"] == "discord")
    assert discord["connected"] is False
    assert discord["connectMode"] == "config"
    assert discord["credentialsFields"] == [
        {
            "name": "bot_token",
            "label": "Bot Token",
            "secret": True,
            "placeholder": "MTAxxx.Gxxxx.xxxxx",
        }
    ]

    assert {a["name"] for a in body["builtinActions"]} == {"web_search", "web_fetch", "http"}
