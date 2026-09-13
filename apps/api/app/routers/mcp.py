"""The `/mcp` API: register MCP servers and keep their tool listings fresh.

Registering a server is two things at once — a row, and a connection attempt. Both happen
here, in that order, and the connection attempt is allowed to fail: a server whose command
is wrong is still *registered* (201), with the failure on `lastError` for the user to fix,
because the alternative is an endpoint that rejects the row and loses everything the user
typed. `POST /mcp/servers/test` is the way to check a config before saving it.

Writes are also the only place that talks to an MCP server: reads (`GET /mcp/servers`,
`GET /tools`) serve the cached listing. See `app.services.mcp_servers`.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.base import get_session
from app.db.models import McpServer
from app.errors import NotFound
from app.mcp import McpServerConfig, get_manager
from app.mcp import test_server as probe_server
from app.schemas.mcp import (
    CreateMcpServerRequest,
    McpServerListResponse,
    McpServerPayload,
    PatchMcpServerRequest,
    TestMcpServerRequest,
    TestMcpServerResponse,
    UpdateMcpServerRequest,
)
from app.services import mcp_servers as svc
from app.utils import to_ms

router = APIRouter(prefix="/mcp", tags=["mcp"])
log = structlog.get_logger("app.mcp.router")

DBSession = Annotated[AsyncSession, Depends(get_session)]


def _payload(server: McpServer) -> McpServerPayload:
    view = svc.public_view(server)
    synced = view.pop("last_synced_at", None)
    view["last_synced_at"] = to_ms(synced) if synced is not None else None
    return McpServerPayload.model_validate(view)


async def _load(session: AsyncSession, server_id: str) -> McpServer:
    server = await svc.get_server(session, server_id)
    if server is None:
        raise NotFound(f"MCP server {server_id} not found.")
    return server


@router.get("/servers", response_model=McpServerListResponse)
async def list_mcp_servers(user: CurrentUser, session: DBSession) -> McpServerListResponse:
    """Every registered server with its cached tool count and last sync outcome."""
    servers = await svc.list_servers(session)
    return McpServerListResponse(servers=[_payload(s) for s in servers])


@router.post("/servers", response_model=McpServerPayload, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: CreateMcpServerRequest, user: CurrentUser, session: DBSession
) -> McpServerPayload:
    """Register a server and sync its tools. A failed sync still returns 201."""
    server = await svc.create_server(
        session,
        name=body.name,
        transport=body.transport,
        config=body.config,
        allow_private_network=body.allow_private_network,
        enabled=body.enabled,
    )
    if server.enabled:
        await svc.sync_server(session, server)
    return _payload(server)


@router.put("/servers/{server_id}", response_model=McpServerPayload)
async def update_mcp_server(
    server_id: str, body: UpdateMcpServerRequest, user: CurrentUser, session: DBSession
) -> McpServerPayload:
    """Update a server (partial) and re-sync it, since anything here can change its tools."""
    server = await _load(session, server_id)
    await svc.update_server(
        session,
        server,
        name=body.name,
        transport=body.transport,
        config=body.config,
        allow_private_network=body.allow_private_network,
        enabled=body.enabled,
    )
    # The stored config changed under the pooled connection; drop it so the sync (and
    # every later call) connects with what was just saved.
    await get_manager().disconnect(server.name)
    if server.enabled:
        await svc.sync_server(session, server)
    return _payload(server)


@router.patch("/servers/{server_id}", response_model=McpServerPayload)
async def patch_mcp_server(
    server_id: str, body: PatchMcpServerRequest, user: CurrentUser, session: DBSession
) -> McpServerPayload:
    """Enable or disable a server.

    Disabling drops its tools from the catalog and the agent's tool list immediately (the
    catalog only reads enabled servers) and closes the connection; re-enabling re-syncs,
    because the listing may be stale by then.
    """
    server = await _load(session, server_id)
    await svc.update_server(session, server, enabled=body.enabled)
    if not server.enabled:
        await get_manager().disconnect(server.name)
    else:
        await svc.sync_server(session, server)
    return _payload(server)


@router.post("/servers/{server_id}/refresh", response_model=McpServerPayload)
async def refresh_mcp_server(
    server_id: str, user: CurrentUser, session: DBSession
) -> McpServerPayload:
    """Re-read the server's tool list into `cachedTools`."""
    server = await _load(session, server_id)
    await svc.sync_server(session, server)
    return _payload(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str, user: CurrentUser, session: DBSession
) -> Response:
    """Unregister a server and close its connection."""
    server = await _load(session, server_id)
    await svc.delete_server(session, server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/test", response_model=TestMcpServerResponse)
async def test_mcp_server(
    body: TestMcpServerRequest, user: CurrentUser, session: DBSession
) -> TestMcpServerResponse:
    """Try a config without saving it: `{ok, tools}` or `{ok: false, error}`.

    Always a 200 — "this config does not work, here is why" is the answer to the
    question, not a failure to answer it.
    """
    transport = svc.validate_transport(body.transport)
    config = svc.normalize_config(transport, body.config)
    result = await probe_server(
        McpServerConfig(
            name="test",
            transport=transport,  # type: ignore[arg-type]
            config=config,
            allow_private_network=body.allow_private_network,
        )
    )
    return TestMcpServerResponse.model_validate(result)
