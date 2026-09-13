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

import asyncio
import contextlib
import re
import socket
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import Settings
from app.errors import Forbidden, ToolError
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
ECHO_TOOLS = {"echo", "add", "fail", "crash", "slow"}


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
    assert identifier.startswith("mcp__echo__get_thing_v2_")
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier)
    # The original name is recoverable even though the id no longer spells it.
    assert parse_tool_id(identifier) == ("echo", "get/thing v2")


def test_sanitized_tool_names_do_not_collide() -> None:
    """`get.thing` and `get_thing` must not both become `mcp__echo__get_thing`.

    Sanitizing is many-to-one, so the id of a name that had to be changed carries a
    digest of the original — otherwise one of the two tools would silently dispatch to
    the other.
    """
    dotted = tool_id("echo", "get.thing")
    plain = tool_id("echo", "get_thing")
    slashed = tool_id("echo", "get/thing")

    assert plain == "mcp__echo__get_thing"  # unchanged names keep the readable id
    assert len({dotted, plain, slashed}) == 3
    assert parse_tool_id(dotted) == ("echo", "get.thing")
    assert parse_tool_id(plain) == ("echo", "get_thing")
    assert parse_tool_id(slashed) == ("echo", "get/thing")


def test_parse_tool_id_handles_underscores_in_a_server_name() -> None:
    identifier = tool_id("a_b", "x__y")
    assert identifier == "mcp__a_b__x__y"
    assert parse_tool_id(identifier) == ("a_b", "x__y")


def test_parse_tool_id_uses_the_registered_server_names() -> None:
    """`mcp__a__b__x` is ambiguous: server `a__b` + tool `x`, or server `a` + `b__x`?

    The reverse map settles it for ids this process minted; the registered server names
    settle it for an id that came back from the database in a later process.
    """
    from app.mcp import schemas as mcp_schemas

    identifier = tool_id("a__b", "x")
    assert identifier == "mcp__a__b__x"
    assert parse_tool_id(identifier) == ("a__b", "x")

    mcp_schemas._REVERSE_IDS.pop(identifier, None)
    assert parse_tool_id(identifier, known_servers=["a", "a__b"]) == ("a__b", "x")
    # Without the server list, the plain split is the documented best effort.
    assert parse_tool_id(identifier) == ("a", "b__x")


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


# ─── the stdio gate ──────────────────────────────────────────────────────────────────


def _settings(**overrides: str) -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@db/x",
        ENCRYPTION_KEY="cGx1bWVhaS1kZXYtZW5jLWtleS0zMmJ5dGVzLXBhZCE=",
        **overrides,
    )


@pytest.mark.parametrize(
    ("app_env", "flag", "expected"),
    [
        ("dev", None, True),  # development: on, so the feature is usable out of the box
        ("dev", "", True),  # compose passes an empty string when the var is unset
        ("dev", "false", False),
        ("production", None, False),  # anywhere else: off unless explicitly allowed
        ("production", "true", True),
        ("production", "1", True),
        ("production", "maybe", False),  # a typo fails closed, never open
    ],
)
def test_stdio_allowed_default(app_env: str, flag: str | None, expected: bool) -> None:
    overrides = {"APP_ENV": app_env}
    if flag is not None:
        overrides["MCP_ALLOW_STDIO"] = flag
    assert _settings(**overrides).mcp_allow_stdio is expected


def test_assert_stdio_allowed_refuses_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(mcp_manager, "stdio_allowed", lambda: False)

    with pytest.raises(Forbidden):
        mcp_manager.assert_stdio_allowed("stdio")
    mcp_manager.assert_stdio_allowed("http")  # unaffected


async def test_connecting_to_a_stdio_server_is_refused_when_disabled(
    manager: mcp_manager.McpManager, monkeypatch
) -> None:
    """Defense in depth: a row registered while stdio was allowed stops working."""
    monkeypatch.setattr(mcp_manager, "stdio_allowed", lambda: False)

    with pytest.raises(ToolError) as excinfo:
        await manager.list_tools(echo_config())
    assert excinfo.value.extra.get("retryable") is False


# ─── listing ─────────────────────────────────────────────────────────────────────────


async def test_list_tools_reads_the_server(manager: mcp_manager.McpManager) -> None:
    tools = await manager.list_tools(echo_config())

    by_name = {t.name: t for t in tools}
    assert set(by_name) == ECHO_TOOLS
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
    assert {t.name for t in tools} == ECHO_TOOLS


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


# ─── HTTP transport ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def http_echo_server() -> AsyncIterator[str]:
    """The same fixture server, served over Streamable HTTP on a loopback port.

    Loopback is exactly what `assert_public_url` refuses, so every test using this passes
    `allow_private_network=True` — which is also the only way the opt-out gets covered
    end to end rather than only at the point where it skips the guard.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        ECHO_SERVER,
        "--http",
        str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                break
            await asyncio.sleep(0.1)
        else:  # pragma: no cover — the fixture server failed to start
            pytest.fail("the HTTP echo server never started listening")
        yield url
    finally:
        process.terminate()
        with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
            await asyncio.wait_for(process.wait(), 5)


def http_config(url: str) -> McpServerConfig:
    return McpServerConfig(
        name="http-echo",
        transport="http",
        config={"url": url, "headers": {"X-Test": "1"}},
        allow_private_network=True,
    )


async def test_streamable_http_transport_works(
    manager: mcp_manager.McpManager, http_echo_server: str
) -> None:
    cfg = http_config(http_echo_server)

    tools = await manager.list_tools(cfg)
    assert {t.name for t in tools} == ECHO_TOOLS

    result = await manager.call_tool(cfg, "echo", {"text": "over http"})
    assert result.ok is True
    assert result.content == "echo: over http"


async def test_test_server_over_http(http_echo_server: str) -> None:
    result = await mcp_manager.test_server(http_config(http_echo_server))

    assert result["ok"] is True
    assert {t["name"] for t in result["tools"]} == ECHO_TOOLS


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


# ─── a connection that dies under us ─────────────────────────────────────────────────


async def test_a_dead_server_is_detected_and_replaced(manager: mcp_manager.McpManager) -> None:
    """The `crash` tool kills the process mid-request. The next call must work.

    Without fatal-failure detection the SDK answers `Connection closed` to this and to
    every call after it, forever: the pool would keep a connection that can never work
    again (and, for stdio, never reap the subprocess).
    """
    cfg = echo_config()
    assert (await manager.call_tool(cfg, "echo", {"text": "before"})).ok is True

    with pytest.raises(ToolError):
        await manager.call_tool(cfg, "crash", {})

    # The dead connection is gone rather than lingering as "alive".
    assert manager.connected_names() == []

    result = await manager.call_tool(cfg, "echo", {"text": "after"})
    assert result.ok is True
    assert result.content == "echo: after"


async def test_list_tools_recovers_from_a_dead_server(manager: mcp_manager.McpManager) -> None:
    cfg = echo_config()
    await manager.list_tools(cfg)
    with pytest.raises(ToolError):
        await manager.call_tool(cfg, "crash", {})

    tools = await manager.list_tools(cfg, refresh=True)
    assert {t.name for t in tools} == ECHO_TOOLS


# ─── cancellation and concurrency ────────────────────────────────────────────────────


async def test_cancelling_a_caller_cancels_the_call(
    manager: mcp_manager.McpManager, tmp_path: Path
) -> None:
    """A cancelled run (or a step timeout) must not leave the tool running."""
    cfg = echo_config()
    marker = tmp_path / "slow.marker"
    task = asyncio.create_task(
        manager.call_tool(cfg, "slow", {"seconds": 3, "marker": str(marker)})
    )
    await asyncio.sleep(0.7)  # long enough to be in flight, far short of 3s
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(1.0)
    assert not marker.exists(), "the tool kept running after its caller was cancelled"

    # …and the connection is still usable.
    assert (await manager.call_tool(cfg, "echo", {"text": "still here"})).ok is True


async def test_concurrent_calls_to_one_server_overlap(
    manager: mcp_manager.McpManager,
) -> None:
    """One session multiplexes: three 1s calls take ~1s, not ~3s."""
    cfg = echo_config()
    await manager.list_tools(cfg)  # pay for the connection before timing anything

    started = time.monotonic()
    results = await asyncio.gather(
        *(manager.call_tool(cfg, "slow", {"seconds": 1}) for _ in range(3))
    )
    elapsed = time.monotonic() - started

    assert all(r.ok for r in results)
    assert elapsed < 2.0, f"calls serialized ({elapsed:.1f}s for 3 x 1s)"


# ─── test_server ─────────────────────────────────────────────────────────────────────


async def test_test_server_reports_the_tools() -> None:
    result = await mcp_manager.test_server(echo_config("probe"))

    assert result["ok"] is True
    assert {t["name"] for t in result["tools"]} == ECHO_TOOLS
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
