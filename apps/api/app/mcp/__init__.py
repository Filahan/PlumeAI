"""Generic MCP (Model Context Protocol) client.

`app.mcp.schemas` holds the pure value types and the naming rules that put an MCP tool
into PlumeAI's flat tool namespace; `app.mcp.manager` owns the live connections. The
database side (registration, encryption, cached tool listings) lives in
`app.services.mcp_servers`, and the HTTP surface in `app.routers.mcp`.
"""

from __future__ import annotations

from app.mcp.manager import (
    DEFAULT_CALL_TIMEOUT,
    STDIO_DISABLED_MESSAGE,
    McpManager,
    assert_stdio_allowed,
    close_all,
    get_manager,
    stdio_allowed,
    test_server,
)
from app.mcp.schemas import (
    SERVER_NAME_RE,
    TRANSPORTS,
    McpServerConfig,
    McpToolInfo,
    Transport,
    humanize_tool,
    integration_name,
    is_mcp_tool_id,
    parse_integration_name,
    parse_tool_id,
    to_openai_schema,
    tool_id,
)

__all__ = [
    "DEFAULT_CALL_TIMEOUT",
    "SERVER_NAME_RE",
    "STDIO_DISABLED_MESSAGE",
    "TRANSPORTS",
    "McpManager",
    "McpServerConfig",
    "McpToolInfo",
    "Transport",
    "assert_stdio_allowed",
    "close_all",
    "get_manager",
    "humanize_tool",
    "integration_name",
    "is_mcp_tool_id",
    "parse_integration_name",
    "parse_tool_id",
    "stdio_allowed",
    "test_server",
    "to_openai_schema",
    "tool_id",
]
