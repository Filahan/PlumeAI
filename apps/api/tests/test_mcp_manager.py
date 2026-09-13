"""The MCP client against a real MCP server.

Nothing here is mocked: `tests/fixtures/echo_mcp_server.py` is a genuine stdio MCP server
(the SDK's own `MCPServer`) launched as a subprocess, because the parts of this feature
worth testing are exactly the parts a fake would get wrong — the handshake, the shape of
a `CallToolResult`, and what happens when the process is gone.

Every test closes its connection: the manager is keyed by event loop
(`app.mcp.manager.get_manager`) and each test gets a fresh loop, but the subprocess would
outlive the test if nothing closed it.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from app.errors import ToolError
from app.mcp import manager as mcp_manager
from app.mcp.schemas import (
    McpServerConfig,
    McpToolInfo,
    is_mcp_tool_id,
    parse_tool_id,
    to_openai_schema,
    tool_id,
)

ECHO_SERVER = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


def echo_config(name: str = "echo") -> McpServerConfig:
    return McpServerConfig(
        name=name,
        transport="stdio",
        config={"command": sys.executable, "args": [ECHO_SERVER], "env": {}},
    )


@pytest_asyncio.fixture
async def manager() -> AsyncIterator[mcp_manager.McpManager]:
    mgr = mcp_manager.get_manager()
    try:
        yield mgr
    finally:
        await mgr.close_all()


# ─── tool ids ────────────────────────────────────────────────────────────────────────


def test_tool_id_round_trips() -> None:
    identifier = tool_id("echo", "echo")
    assert identifier == "mcp__echo__echo"
    assert is_mcp_tool_id(identifier)
    assert parse_tool_id(identifier) == ("echo", "echo")


def test_tool_id_sanitizes_illegal_characters() -> None:
    identifier = tool_id("echo", "get/thing v2")
    assert identifier == "mcp__echo__get_thing_v2"
    # The original name is recoverable even though the id no longer spells it.
    assert parse_tool_id(identifier) == ("echo", "get/thing v2")


def test_tool_id_truncates_to_a_legal_function_name() -> None:
    long_name = "a" * 120
    identifier = tool_id("echo", long_name)
    assert len(identifier) <= 64
    assert parse_tool_id(identifier) == ("echo", long_name)


def test_tool_id_survives_a_tool_name_containing_the_separator() -> None:
    identifier = tool_id("echo", "do__thing")
    assert parse_tool_id(identifier) == ("echo", "do__thing")


def test_parse_tool_id_rejects_non_mcp_names() -> None:
    assert parse_tool_id("gmail_search") is None
    assert parse_tool_id("mcp__echo") is None
    assert not is_mcp_tool_id("gmail_search")


def test_to_openai_schema_shape() -> None:
    tool = McpToolInfo(
        name="echo",
        description="Echo the given text back.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    schema = to_openai_schema("echo", tool)

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp__echo__echo"
    assert schema["function"]["description"] == "[echo] Echo the given text back."
    assert schema["function"]["parameters"] == tool.input_schema
    # Never a live reference to the cached schema.
    assert schema["function"]["parameters"] is not tool.input_schema


def test_to_openai_schema_defaults_empty_parameters() -> None:
    schema = to_openai_schema("echo", McpToolInfo(name="fail"))
    assert schema["function"]["parameters"] == {"type": "object", "properties": {}}
    assert schema["function"]["description"] == "[echo] fail"


# ─── listing ─────────────────────────────────────────────────────────────────────────


async def test_list_tools_reads_the_server(manager: mcp_manager.McpManager) -> None:
    tools = await manager.list_tools(echo_config())

    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"echo", "add", "fail"}
    assert by_name["echo"].description == "Echo the given text back."
    assert by_name["echo"].input_schema["properties"]["text"]["type"] == "string"
    assert by_name["add"].input_schema["required"] == ["a", "b"]


async def test_list_tools_is_cached_until_refreshed(manager: mcp_manager.McpManager) -> None:
    cfg = echo_config()
    first = await manager.list_tools(cfg)
    assert await manager.list_tools(cfg) is first  # same list object → no round trip
    refreshed = await manager.list_tools(cfg, refresh=True)
    assert refreshed is not first
    assert [t.name for t in refreshed] == [t.name for t in first]


# ─── calling ─────────────────────────────────────────────────────────────────────────


async def test_call_tool_returns_text_content(manager: mcp_manager.McpManager) -> None:
    result = await manager.call_tool(echo_config(), "echo", {"text": "hi"})

    assert result.ok is True
    assert result.content == "echo: hi"


async def test_call_tool_returns_structured_content(manager: mcp_manager.McpManager) -> None:
    result = await manager.call_tool(echo_config(), "add", {"a": 2, "b": 3})

    assert result.ok is True
    assert result.data == {"sum": 5}


async def test_call_tool_maps_is_error_to_a_failed_result(
    manager: mcp_manager.McpManager,
) -> None:
    result = await manager.call_tool(echo_config(), "fail", {})

    assert result.ok is False
    assert "fail" in result.content
    assert result.retryable is True


async def test_call_tool_maps_an_unknown_tool_to_a_failed_result(
    manager: mcp_manager.McpManager,
) -> None:
    """The server answers `isError` rather than raising, and so do we."""
    result = await manager.call_tool(echo_config(), "nope", {})

    assert result.ok is False
    assert "nope" in result.content


# ─── connection lifecycle ────────────────────────────────────────────────────────────


async def test_reconnects_after_disconnect(manager: mcp_manager.McpManager) -> None:
    cfg = echo_config()
    assert (await manager.call_tool(cfg, "echo", {"text": "one"})).content == "echo: one"
    assert manager.connected_names() == ["echo"]

    await manager.disconnect("echo")
    assert manager.connected_names() == []

    assert (await manager.call_tool(cfg, "echo", {"text": "two"})).content == "echo: two"
    assert manager.connected_names() == ["echo"]


async def test_changing_the_config_replaces_the_connection(
    manager: mcp_manager.McpManager,
) -> None:
    cfg = echo_config()
    await manager.list_tools(cfg)
    changed = McpServerConfig(
        name="echo",
        transport="stdio",
        config={"command": sys.executable, "args": [ECHO_SERVER], "env": {"X": "1"}},
    )
    assert changed.fingerprint != cfg.fingerprint

    tools = await manager.list_tools(changed)
    assert {t.name for t in tools} == {"echo", "add", "fail"}


async def test_close_all_closes_every_connection(manager: mcp_manager.McpManager) -> None:
    await manager.list_tools(echo_config("one"))
    await manager.list_tools(echo_config("two"))
    assert manager.connected_names() == ["one", "two"]

    await manager.close_all()
    assert manager.connected_names() == []


async def test_a_command_that_does_not_exist_raises_tool_error(
    manager: mcp_manager.McpManager,
) -> None:
    cfg = McpServerConfig(
        name="broken", transport="stdio", config={"command": "definitely-not-a-command"}
    )
    with pytest.raises(ToolError):
        await manager.list_tools(cfg)


async def test_a_stdio_config_without_a_command_is_permanent(
    manager: mcp_manager.McpManager,
) -> None:
    cfg = McpServerConfig(name="broken", transport="stdio", config={})
    with pytest.raises(ToolError) as excinfo:
        await manager.list_tools(cfg)
    assert excinfo.value.extra.get("retryable") is False


# ─── HTTP transport guard ────────────────────────────────────────────────────────────


async def test_private_http_url_is_rejected(manager: mcp_manager.McpManager) -> None:
    cfg = McpServerConfig(
        name="local", transport="http", config={"url": "http://localhost:9999/mcp"}
    )
    with pytest.raises(ToolError) as excinfo:
        await manager.list_tools(cfg)
    # The SSRF guard's rejections are permanent — retrying cannot make the URL public.
    assert excinfo.value.extra.get("retryable") is False


async def test_allow_private_network_skips_the_url_guard(
    manager: mcp_manager.McpManager,
) -> None:
    """With the opt-in, the URL is accepted and the *connection* is what fails."""
    cfg = McpServerConfig(
        name="local",
        transport="http",
        config={"url": "http://localhost:9/mcp"},
        allow_private_network=True,
    )
    with pytest.raises(ToolError) as excinfo:
        await manager.list_tools(cfg)
    assert "not allowed" not in str(excinfo.value.detail)


# ─── test_server ─────────────────────────────────────────────────────────────────────


async def test_test_server_reports_the_tools() -> None:
    result = await mcp_manager.test_server(echo_config("probe"))

    assert result["ok"] is True
    assert {t["name"] for t in result["tools"]} == {"echo", "add", "fail"}
    # Probing must not leave a pooled connection behind.
    assert mcp_manager.get_manager().connected_names() == []


async def test_test_server_reports_an_error_instead_of_raising() -> None:
    result = await mcp_manager.test_server(
        McpServerConfig(name="probe", transport="stdio", config={"command": "nope-nope"})
    )

    assert result["ok"] is False
    assert result["error"]
    assert "tools" not in result


async def test_test_server_rejects_a_private_url() -> None:
    result = await mcp_manager.test_server(
        McpServerConfig(name="probe", transport="http", config={"url": "http://127.0.0.1/mcp"})
    )

    assert result["ok"] is False
    assert "private" in result["error"].lower()
