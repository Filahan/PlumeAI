"""Tool dispatch: routes a tool-call name to a builtin, an integration, or an MCP tool.

MCP tools are the only ones whose existence is data rather than code: they are named
`mcp__<server>__<tool>` (see `app.mcp.schemas.tool_id`) and resolved against the cached
listing of the registered servers, so a tool that vanished from a server since the last
sync is rejected here instead of being sent to it.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ProviderError, ToolError
from app.integrations.registry import (
    find_integration_for_function,
    list_configured_integrations,
)
from app.mcp import (
    DEFAULT_CALL_TIMEOUT,
    get_manager,
    is_mcp_tool_id,
    parse_tool_id,
    to_openai_schema,
    tool_id,
)
from app.services import mcp_servers as mcp_service
from app.tools.base import ToolResult, safe_json_args
from app.tools.builtin import BUILTIN_DISPATCH, BUILTIN_NAMES, BUILTIN_SCHEMAS

log = structlog.get_logger("app.tools.registry")


def builtin_tool_schemas() -> list[dict[str, Any]]:
    """The always-on built-in tool schemas (web_search, web_fetch, http)."""
    return list(BUILTIN_SCHEMAS)


async def mcp_tool_schemas(session: AsyncSession) -> list[dict[str, Any]]:
    """One function schema per tool of every *enabled* MCP server.

    Read from `mcp_servers.cached_tools`, never from the servers themselves: this runs
    before every agent turn and every automation step, and a slow (or dead) MCP server
    must not slow down (or break) the ones that work.

    A server whose last sync failed advertises nothing, which is the same answer
    `app.services.mcp_servers.is_connected` gives the catalog and the builder: offering
    the model a tool we already know we cannot reach buys a failed step instead of a
    "that integration is not connected" it can act on. The *catalog* still lists those
    actions (documents that already use them must keep validating, with a warning) — the
    live tool list does not.
    """
    schemas: list[dict[str, Any]] = []
    for server in await mcp_service.list_servers(session, enabled_only=True):
        if not mcp_service.is_connected(server):
            continue
        for tool in mcp_service.cached_tools(server):
            schemas.append(to_openai_schema(server.name, tool))
    return schemas


async def list_available_tool_schemas(session: AsyncSession) -> list[dict[str, Any]]:
    """Built-ins + all integrations the user has currently connected + MCP tools."""
    schemas: list[dict[str, Any]] = list(BUILTIN_SCHEMAS)
    for integ in await list_configured_integrations(session):
        schemas.extend(integ.schemas)
    schemas.extend(await mcp_tool_schemas(session))
    return schemas


def _is_retryable(exc: AppError) -> bool:
    """Whether another attempt of a tool call that raised `exc` could do better.

    A bare `ToolError` is the generic runtime failure (a timeout, an upstream hiccup) and
    is worth retrying unless it says otherwise. Every *other* `AppError` — a disconnected
    integration (`ToolNotConfigured`), a bad argument (`BadRequest`), a missing resource
    (`NotFound`) — is the tool rejecting the request, which it will do identically next
    time. `extra={"retryable": False}` lets a `ToolError` opt out (the SSRF guard does).
    """
    if isinstance(exc, ProviderError):
        # An upstream service misbehaved mid-call (e.g. Google's token endpoint returned a
        # 5xx while refreshing) — its 502 semantics: the next attempt may well succeed.
        return True
    if not isinstance(exc, ToolError):
        return False
    return bool(exc.extra.get("retryable", True))


async def execute_mcp_tool(
    name: str, args: dict[str, Any], session: AsyncSession
) -> ToolResult:
    """Dispatch one `mcp__<server>__<tool>` call to its server.

    Every rejection here is permanent (`retryable=False`): an unparseable id, a server
    that was deleted or disabled, a tool the server no longer advertises — none of that
    changes on a second attempt, and the automation executor should surface it to the
    author rather than spend its retry budget on it.
    """
    servers = await mcp_service.list_servers(session)
    parsed = parse_tool_id(name, known_servers=[s.name for s in servers])
    if parsed is None:
        return ToolResult(ok=False, content=f"Unknown tool: {name}", retryable=False)
    server_name, tool_name = parsed

    server = next((s for s in servers if s.name == server_name), None)
    if server is None:
        return ToolResult(
            ok=False, content=f"Unknown MCP server: {server_name}", retryable=False
        )
    if not server.enabled:
        return ToolResult(
            ok=False,
            content=f"MCP server '{server_name}' is disabled.",
            retryable=False,
        )

    # The id may be a sanitized or truncated spelling of the real tool name (and the
    # reverse map only knows the ids *this* process minted), so the authoritative match
    # is the one that re-derives the id from each cached tool.
    tools = mcp_service.cached_tools(server)
    tool = next(
        (t for t in tools if t.name == tool_name or tool_id(server.name, t.name) == name),
        None,
    )
    if tool is None:
        return ToolResult(
            ok=False,
            content=f"MCP server '{server_name}' has no tool named '{tool_name}'.",
            retryable=False,
        )

    return await get_manager().call_tool(
        mcp_service.server_config(server), tool.name, args, timeout=DEFAULT_CALL_TIMEOUT
    )


async def execute_tool(name: str, raw_args: str, session: AsyncSession) -> ToolResult:
    """Dispatch a tool call. Errors are wrapped into a failed `ToolResult` so the agent
    loop can feed the error back to the LLM rather than killing the stream.

    A failed result also carries `retryable`, which is what the automation executor reads
    to decide whether to spend another attempt on the step (see `_is_retryable`).
    """
    args = safe_json_args(raw_args)
    try:
        if name in BUILTIN_NAMES:
            return await BUILTIN_DISPATCH[name](args)
        if is_mcp_tool_id(name):
            return await execute_mcp_tool(name, args, session)
        integ = find_integration_for_function(name)
        if integ is not None:
            return await integ.execute(name, args, session)
        return ToolResult(ok=False, content=f"Unknown tool: {name}", retryable=False)
    except AppError as exc:
        retryable = _is_retryable(exc)
        log.warning(
            "tool_error",
            tool=name,
            exc_type=type(exc).__name__,
            retryable=retryable,
            exc_info=True,
        )
        return ToolResult(ok=False, content=f"Error: {exc.detail}", retryable=retryable)
    except Exception as exc:  # noqa: BLE001
        log.warning("tool_error", tool=name, exc_type=type(exc).__name__, exc_info=True)
        return ToolResult(ok=False, content=f"Error: {exc}")
