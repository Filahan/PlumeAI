"""The `/mcp` API and everything downstream of a registered MCP server.

The server under test is the real stdio one from `tests/fixtures/echo_mcp_server.py`, so
these tests cover the whole path a user's MCP tool travels: registered over HTTP →
encrypted in `mcp_servers` → cached listing → `GET /tools` → the agent's tool schemas →
`execute_tool` → an action step of a document the executor runs.

Every test closes the pooled connections at the end (`_close_mcp_connections`), or the
stdio subprocess would outlive the event loop it was spawned on.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.db.models import McpServer
from app.mcp import manager as mcp_manager
from app.schemas.documents import AutomationDocument
from app.services import automations as svc
from app.services import mcp_servers as mcp_service
from app.services import runs as runs_svc
from app.services.assistant_prompt import format_catalog
from app.services.catalog import build_catalog
from app.services.documents import validate_document
from app.services.executor import execute_run
from app.tools.registry import execute_tool, list_available_tool_schemas

ECHO_SERVER = str(Path(__file__).parents[1] / "fixtures" / "echo_mcp_server.py")
SECRET_VALUE = "s3cr3t-token-value"
ECHO_TOOLS = {"echo", "add", "fail", "crash", "slow"}

ECHO_BODY: dict[str, Any] = {
    "name": "echo",
    "transport": "stdio",
    "config": {
        "command": sys.executable,
        "args": [ECHO_SERVER],
        "env": {"ECHO_TOKEN": SECRET_VALUE},
    },
}


@pytest.fixture(autouse=True)
async def _close_mcp_connections():
    yield
    await mcp_manager.get_manager().close_all()


async def _register(client) -> dict[str, Any]:
    response = await client.post("/mcp/servers", json=ECHO_BODY)
    assert response.status_code == 201, response.text
    return response.json()


# ─── registration ────────────────────────────────────────────────────────────────────


async def test_create_server_connects_and_caches_its_tools(client) -> None:
    payload = await _register(client)

    assert payload["name"] == "echo"
    assert payload["transport"] == "stdio"
    assert payload["enabled"] is True
    assert payload["connected"] is True
    assert payload["lastError"] is None
    assert payload["toolCount"] == len(ECHO_TOOLS)
    assert {t["name"] for t in payload["tools"]} == ECHO_TOOLS
    assert payload["lastSyncedAt"] > 0


async def test_create_server_never_echoes_the_env_values(client) -> None:
    response = await client.post("/mcp/servers", json=ECHO_BODY)

    assert SECRET_VALUE not in response.text
    payload = response.json()
    assert payload["envNames"] == ["ECHO_TOKEN"]
    assert payload["command"] == sys.executable
    assert payload["args"] == [ECHO_SERVER]
    assert payload["url"] is None


async def test_the_stored_config_is_encrypted(client, engine) -> None:
    await _register(client)

    async with engine.begin() as conn:
        row = (
            await conn.execute(sa.text("SELECT name, config_enc FROM mcp_servers"))
        ).mappings().one()

    raw = str(row["config_enc"])
    assert SECRET_VALUE not in raw
    assert sys.executable not in raw
    assert "command" not in raw
    assert set(row["config_enc"]) == {"ciphertext", "iv"}


async def test_a_broken_command_is_still_registered_with_its_error(client) -> None:
    response = await client.post(
        "/mcp/servers",
        json={"name": "broken", "transport": "stdio", "config": {"command": "nope-nope"}},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["connected"] is False
    assert payload["toolCount"] == 0
    assert payload["lastError"]


async def test_duplicate_name_is_a_conflict(client) -> None:
    await _register(client)
    response = await client.post("/mcp/servers", json=ECHO_BODY)
    assert response.status_code == 409


async def test_an_invalid_name_is_rejected(client) -> None:
    response = await client.post(
        "/mcp/servers",
        json={"name": "Echo Server!", "transport": "stdio", "config": {"command": "x"}},
    )
    assert response.status_code == 422


async def test_a_stdio_config_without_a_command_is_rejected(client) -> None:
    response = await client.post(
        "/mcp/servers", json={"name": "nocmd", "transport": "stdio", "config": {}}
    )
    assert response.status_code == 400


async def test_a_private_http_url_is_registered_but_not_connected(client) -> None:
    response = await client.post(
        "/mcp/servers",
        json={
            "name": "private",
            "transport": "http",
            "config": {
                "url": "http://localhost:9999/mcp",
                "headers": {"Authorization": SECRET_VALUE},
            },
        },
    )

    assert response.status_code == 201
    assert SECRET_VALUE not in response.text
    payload = response.json()
    assert payload["connected"] is False
    assert payload["headerNames"] == ["Authorization"]
    assert payload["url"] == "http://localhost:9999/mcp"
    assert "not allowed" in payload["lastError"]


# ─── list / update / refresh / delete ────────────────────────────────────────────────


async def test_list_servers(client) -> None:
    await _register(client)

    response = await client.get("/mcp/servers")

    assert response.status_code == 200
    assert SECRET_VALUE not in response.text
    servers = response.json()["servers"]
    assert [s["name"] for s in servers] == ["echo"]
    assert servers[0]["connected"] is True


async def test_refresh_re_reads_the_tools(client, session) -> None:
    created = await _register(client)
    # Simulate a stale cache, then prove a refresh repopulates it from the server.
    server = await mcp_service.get_server(session, created["id"])
    await mcp_service.set_cached_tools(session, server, [], error="stale")
    await session.commit()

    response = await client.post(f"/mcp/servers/{created['id']}/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["toolCount"] == len(ECHO_TOOLS)
    assert payload["lastError"] is None
    assert payload["connected"] is True


async def test_update_replaces_the_config_and_re_syncs(client) -> None:
    created = await _register(client)

    response = await client.put(
        f"/mcp/servers/{created['id']}",
        json={"config": {"command": sys.executable, "args": [ECHO_SERVER], "env": {}}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["envNames"] == []
    assert payload["toolCount"] == len(ECHO_TOOLS)


async def test_update_can_rename(client) -> None:
    created = await _register(client)

    response = await client.put(f"/mcp/servers/{created['id']}", json={"name": "echo2"})

    assert response.status_code == 200
    assert response.json()["name"] == "echo2"
    assert response.json()["toolCount"] == len(ECHO_TOOLS)


async def test_delete_removes_the_server(client) -> None:
    created = await _register(client)

    assert (await client.delete(f"/mcp/servers/{created['id']}")).status_code == 204
    assert (await client.get("/mcp/servers")).json()["servers"] == []
    assert (await client.post(f"/mcp/servers/{created['id']}/refresh")).status_code == 404


async def test_test_endpoint_probes_without_saving(client) -> None:
    response = await client.post(
        "/mcp/servers/test",
        json={"transport": "stdio", "config": {"command": sys.executable, "args": [ECHO_SERVER]}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert {t["name"] for t in body["tools"]} == ECHO_TOOLS
    # Nothing was persisted.
    assert (await client.get("/mcp/servers")).json()["servers"] == []


async def test_test_endpoint_reports_a_failure_as_a_200(client) -> None:
    response = await client.post(
        "/mcp/servers/test", json={"transport": "stdio", "config": {"command": "nope-nope"}}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"]


# ─── catalog + registry ──────────────────────────────────────────────────────────────


async def test_get_tools_lists_the_mcp_server_and_its_actions(client) -> None:
    await _register(client)

    catalog = (await client.get("/tools")).json()

    servers = catalog["mcpServers"]
    assert [s["name"] for s in servers] == ["echo"]
    server = servers[0]
    assert server["connected"] is True
    assert server["transport"] == "stdio"
    action = next(a for a in server["actions"] if a["name"] == "mcp__echo__echo")
    assert action["integration"] == "mcp:echo"
    # The server declares a `title`, which beats humanizing the function name…
    assert action["label"] == "Echo text"
    # …and its output schema travels with the action, for the builder's `{{step.output}}`.
    assert action["outputSchema"]["type"] == "object"
    add_action = next(a for a in server["actions"] if a["name"] == "mcp__echo__add")
    assert add_action["label"] == "Add"  # no title → humanized function name
    assert action["description"] == "Echo the given text back."
    assert action["inputSchema"]["properties"]["text"]["type"] == "string"


async def test_tool_schemas_include_the_mcp_tools(client, session) -> None:
    await _register(client)

    schemas = await list_available_tool_schemas(session)

    names = {s["function"]["name"] for s in schemas}
    assert {"mcp__echo__echo", "mcp__echo__add", "mcp__echo__fail"} <= names


async def test_disabling_a_server_removes_its_tools_everywhere(client, session) -> None:
    created = await _register(client)

    response = await client.patch(f"/mcp/servers/{created['id']}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["connected"] is False

    catalog = (await client.get("/tools")).json()
    assert catalog["mcpServers"][0]["actions"] == []

    session.expire_all()
    schemas = await list_available_tool_schemas(session)
    assert not [s for s in schemas if s["function"]["name"].startswith("mcp__")]

    # And re-enabling brings them back (with a fresh sync).
    response = await client.patch(f"/mcp/servers/{created['id']}", json={"enabled": True})
    assert response.json()["connected"] is True
    session.expire_all()
    schemas = await list_available_tool_schemas(session)
    assert any(s["function"]["name"] == "mcp__echo__echo" for s in schemas)


async def test_execute_tool_routes_through_the_registry(client, session) -> None:
    await _register(client)
    session.expire_all()

    result = await execute_tool(
        "mcp__echo__echo", '{"text": "through the registry"}', session
    )

    assert result.ok is True
    assert result.content == "echo: through the registry"


async def test_execute_tool_returns_structured_data(client, session) -> None:
    await _register(client)
    session.expire_all()

    result = await execute_tool("mcp__echo__add", '{"a": 4, "b": 5}', session)

    assert result.ok is True
    assert result.data == {"sum": 9}


async def test_execute_tool_rejects_an_unknown_server_permanently(session) -> None:
    result = await execute_tool("mcp__nosuch__echo", "{}", session)

    assert result.ok is False
    assert result.retryable is False
    assert "nosuch" in result.content


async def test_execute_tool_rejects_a_tool_the_server_does_not_have(client, session) -> None:
    await _register(client)
    session.expire_all()

    result = await execute_tool("mcp__echo__nope", "{}", session)

    assert result.ok is False
    assert result.retryable is False


async def test_execute_tool_rejects_a_disabled_server(client, session) -> None:
    created = await _register(client)
    await client.patch(f"/mcp/servers/{created['id']}", json={"enabled": False})
    session.expire_all()

    result = await execute_tool("mcp__echo__echo", '{"text": "hi"}', session)

    assert result.ok is False
    assert result.retryable is False
    assert "disabled" in result.content


# ─── MCP_ALLOW_STDIO gate ────────────────────────────────────────────────────────────


async def test_stdio_registration_is_refused_when_disabled(client, monkeypatch) -> None:
    """A stdio server is a command the container runs; the gate is the only thing
    between an unauthenticated API and arbitrary code execution."""
    monkeypatch.setattr(mcp_manager, "stdio_allowed", lambda: False)

    response = await client.post("/mcp/servers", json=ECHO_BODY)

    assert response.status_code == 403
    assert (await client.get("/mcp/servers")).json()["servers"] == []


async def test_testing_a_stdio_config_is_refused_when_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_manager, "stdio_allowed", lambda: False)

    response = await client.post(
        "/mcp/servers/test",
        json={"transport": "stdio", "config": {"command": sys.executable}},
    )

    assert response.status_code == 403


async def test_http_registration_is_unaffected_by_the_stdio_gate(client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_manager, "stdio_allowed", lambda: False)

    response = await client.post(
        "/mcp/servers",
        json={"name": "remote", "transport": "http", "config": {"url": "https://example.com/mcp"}},
    )

    assert response.status_code == 201


# ─── secrets in what we hand back ────────────────────────────────────────────────────


async def test_secret_looking_args_are_masked(client) -> None:
    response = await client.post(
        "/mcp/servers",
        json={
            "name": "masked",
            "transport": "stdio",
            "config": {
                "command": sys.executable,
                "args": [ECHO_SERVER, "--api-key=sk-live-12345", "--token", "tok-98765"],
            },
        },
    )

    assert response.status_code == 201
    assert "sk-live-12345" not in response.text
    assert "tok-98765" not in response.text
    assert response.json()["args"][1:] == [
        "--api-key=***",
        "--token",
        "***",
    ]


async def test_url_query_strings_are_masked_in_the_view_and_in_errors(client) -> None:
    response = await client.post(
        "/mcp/servers",
        json={
            "name": "querytoken",
            "transport": "http",
            "config": {"url": "http://localhost:9999/mcp?access_token=super-secret"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert "super-secret" not in response.text
    assert payload["url"] == "http://localhost:9999/mcp?access_token=***"
    # The SSRF rejection quotes the URL it refused — that copy is masked too.
    assert "super-secret" not in (payload["lastError"] or "")


# ─── documents + the executor ────────────────────────────────────────────────────────


def _mcp_action_step(step_id: str = "step_mcp01") -> dict[str, Any]:
    return {
        "id": step_id,
        "name": "Echo something",
        "type": "action",
        "settings": {
            "integration": "mcp:echo",
            "action": "mcp__echo__echo",
            "input": {"text": {"kind": "literal", "value": "from an automation"}},
        },
    }


async def test_a_document_using_an_mcp_action_validates(client, session, make_document) -> None:
    await _register(client)
    session.expire_all()

    catalog = await build_catalog(session)
    assert catalog.find_action("mcp__echo__echo") is not None
    assert catalog.is_connected("mcp:echo") is True

    document = AutomationDocument.model_validate(make_document("MCP", [_mcp_action_step()]))
    validated, issues = validate_document(document, catalog)

    assert [i for i in issues if i.level == "error"] == []
    assert validated.steps[0].valid is True


async def test_the_assistant_prompt_lists_the_mcp_actions(client, session) -> None:
    """The builder assistant has to see MCP actions, or it cannot propose them."""
    await _register(client)
    session.expire_all()

    catalog = await build_catalog(session)
    rendered = format_catalog(catalog)

    assert "mcp:echo (MCP server) — connected:" in rendered
    assert 'integration: "mcp:echo", action: "mcp__echo__echo"' in rendered


async def test_an_mcp_action_on_a_disabled_server_does_not_validate(
    client, session, make_document
) -> None:
    created = await _register(client)
    await client.patch(f"/mcp/servers/{created['id']}", json={"enabled": False})
    session.expire_all()

    catalog = await build_catalog(session)
    document = AutomationDocument.model_validate(make_document("MCP", [_mcp_action_step()]))
    _, issues = validate_document(document, catalog)

    assert [i for i in issues if i.level == "error"]


async def test_the_executor_runs_an_mcp_action_step(client, session, make_document) -> None:
    """End to end: a persisted automation whose only step calls a real MCP server."""
    await _register(client)
    session.expire_all()

    automation = await svc.create_automation(
        session, document=make_document("MCP run", [_mcp_action_step()])
    )
    await session.commit()
    run = await runs_svc.create_run(session, automation, trigger="manual")
    run_id = run.id
    await session.commit()

    await execute_run(run_id)

    session.expire_all()
    run, steps = await runs_svc.get_run(session, run_id)
    assert run.status == "succeeded", run.error
    assert [s.status for s in steps] == ["succeeded"]
    # The echo server wraps a scalar return in `structuredContent`, and structured data
    # is what a step's output is when the tool provides it.
    assert steps[0].output == {"result": "echo: from an automation"}


# ─── encryption / service-level details ──────────────────────────────────────────────


async def test_public_view_hides_secrets(session) -> None:
    server = await mcp_service.create_server(
        session,
        name="hidden",
        transport="http",
        config={"url": "https://example.com/mcp", "headers": {"Authorization": SECRET_VALUE}},
    )
    await session.commit()

    view = mcp_service.public_view(server)

    assert view["header_names"] == ["Authorization"]
    assert SECRET_VALUE not in str(view)
    # The manager still gets the real thing.
    assert mcp_service.server_config(server).config["headers"] == {
        "Authorization": SECRET_VALUE
    }


async def test_a_failed_sync_keeps_the_previous_listing(client, session) -> None:
    created = await _register(client)
    server = await mcp_service.get_server(session, created["id"])

    await mcp_service.update_server(
        session, server, config={"command": "nope-nope", "args": [], "env": {}}
    )
    await mcp_service.sync_server(session, server)
    await session.commit()

    assert server.last_error
    assert len(server.cached_tools) == len(ECHO_TOOLS)  # not wiped by the failure
    assert mcp_service.is_connected(server) is False


async def test_unreadable_config_does_not_break_the_catalog(session) -> None:
    """A blob written under a different ENCRYPTION_KEY is a broken server, not a 500."""
    session.add(
        McpServer(
            id="broken",
            name="broken",
            transport="stdio",
            config_enc={"ciphertext": "not-base64!", "iv": "nope"},
            cached_tools=[],
        )
    )
    await session.commit()

    catalog = await build_catalog(session)

    assert [s.name for s in catalog.mcp_servers] == ["broken"]
    assert catalog.is_connected("mcp:broken") is False
