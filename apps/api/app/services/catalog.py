"""Catalog of tool actions available to the agent: integrations + builtin + MCP, merged
with each integration's connection status.

Backs `GET /tools` so the frontend stops hardcoding the integration catalog (see
`apps/web/src/lib/tools/registry-client.ts`, which this catalog is meant to replace).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import McpServer
from app.integrations.base import Integration
from app.integrations.registry import INTEGRATIONS
from app.mcp import (
    McpToolInfo,
    humanize_tool,
    integration_name,
    parse_integration_name,
    tool_id,
)
from app.services import mcp_servers as mcp_service
from app.tools.base import BUILTIN_INTEGRATION, CatalogAction
from app.tools.builtin import describe_builtin_actions


@dataclass
class CatalogIntegration:
    name: str
    label: str
    description: str
    logo_url: str
    connect_mode: Literal["oauth", "config"]
    setup_url: str
    credentials_namespace: str | None
    credentials_fields: list[dict[str, Any]]
    setup: dict[str, Any]
    connected: bool
    actions: list[CatalogAction]


@dataclass
class CatalogMcpServer:
    """One registered MCP server and the actions its tools contribute.

    `connected` is the same predicate `app.services.mcp_servers.is_connected` applies:
    enabled, synced at least once, and no error from the last sync. `actions` is built
    from the *cached* listing, so a server that is momentarily down still contributes the
    actions the documents referring to it were built against (they validate with a
    "not connected" warning rather than an "unknown action" error).
    """

    name: str
    transport: str
    enabled: bool
    connected: bool
    last_error: str | None
    actions: list[CatalogAction]


@dataclass
class Catalog:
    integrations: list[CatalogIntegration]
    builtin_actions: list[CatalogAction]
    mcp_servers: list[CatalogMcpServer] = field(default_factory=list)
    _index: dict[str, CatalogAction] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Builtins first, then integration actions — a name collision (unlikely, but
        # cheap to guard against) resolves in favor of the integration action. MCP
        # actions cannot collide with either: their names are all `mcp__<server>__<tool>`.
        index: dict[str, CatalogAction] = {a.name: a for a in self.builtin_actions}
        for integ in self.integrations:
            for action in integ.actions:
                index[action.name] = action
        for server in self.mcp_servers:
            for action in server.actions:
                index[action.name] = action
        self._index = index

    def find_action(self, name: str) -> CatalogAction | None:
        return self._index.get(name)

    def is_connected(self, integration: str) -> bool:
        if integration == BUILTIN_INTEGRATION:
            return True
        server_name = parse_integration_name(integration)
        if server_name is not None:
            return any(s.name == server_name and s.connected for s in self.mcp_servers)
        return any(i.name == integration and i.connected for i in self.integrations)


async def _build_integration(integ: Integration, session: AsyncSession) -> CatalogIntegration:
    return CatalogIntegration(
        name=integ.name,
        label=integ.label,
        description=integ.description,
        logo_url=integ.logo_url,
        connect_mode=integ.connect_mode,
        setup_url=integ.setup_url,
        credentials_namespace=integ.credentials_namespace,
        credentials_fields=[
            {"name": f.name, "label": f.label, "secret": f.secret, "placeholder": f.placeholder}
            for f in integ.credentials_fields
        ],
        setup=copy.deepcopy(integ.setup),
        connected=await integ.is_configured(session),
        actions=integ.describe_actions(),
    )


def _mcp_action(server_name: str, tool: McpToolInfo) -> CatalogAction:
    """One MCP tool as a catalog action, under the `mcp:<server>` integration."""
    return CatalogAction(
        name=tool_id(server_name, tool.name),
        integration=integration_name(server_name),
        label=humanize_tool(tool.name),
        description=tool.description,
        input_schema=copy.deepcopy(tool.input_schema),
        output_description="",
        output_schema=None,
    )


def _build_mcp_server(server: McpServer) -> CatalogMcpServer:
    tools = mcp_service.cached_tools(server) if server.enabled else []
    return CatalogMcpServer(
        name=server.name,
        transport=server.transport,
        enabled=bool(server.enabled),
        connected=mcp_service.is_connected(server),
        last_error=server.last_error,
        actions=[_mcp_action(server.name, tool) for tool in tools],
    )


async def build_catalog(session: AsyncSession | None) -> Catalog:
    """Assemble the full catalog: every registered integration (with live connection
    status), the always-on builtin tools, and every registered MCP server.

    MCP tools come from `mcp_servers.cached_tools` — one SELECT, no network: building a
    catalog happens on every document read and every run, and must not depend on a
    third-party server answering.

    `session` may be `None` for callers that only want the *shape* of the catalog and
    have stubbed out whatever would otherwise hit the database (`tests/test_catalog.py`
    does exactly that): the MCP section then comes back empty instead of raising.
    """
    integrations = [await _build_integration(integ, session) for integ in INTEGRATIONS]
    rows = await mcp_service.list_servers(session) if session is not None else []
    servers = [_build_mcp_server(row) for row in rows]
    return Catalog(
        integrations=integrations,
        builtin_actions=describe_builtin_actions(),
        mcp_servers=servers,
    )
