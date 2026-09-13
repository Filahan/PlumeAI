"""Registered MCP servers: CRUD, encryption, and the cached tool listing.

This module is the only thing that reads or writes `mcp_servers` rows. It owns two
invariants the rest of the feature leans on:

1. **The connection config is never stored or returned in the clear.** It goes into
   `config_enc` through `app.crypto.encrypt` on the way in, and comes back out either as
   a `McpServerConfig` for the manager (`server_config`) or as a `public_view` that lists
   only the *names* of environment variables and headers.
2. **Reads never touch the network.** `cached_tools` is the source of truth for the
   catalog and the tool registry; only an explicit sync (`sync_server`, driven by
   `POST /mcp/servers` / `PUT` / `refresh`) talks to the server itself.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.models import McpServer
from app.errors import BadRequest, Conflict
from app.mcp import McpServerConfig, McpToolInfo, get_manager
from app.mcp.schemas import SERVER_NAME_RE, TRANSPORTS

log = structlog.get_logger("app.services.mcp_servers")

# `last_error` is shown in the UI, and its writer is a third-party server's error text.
MAX_ERROR_CHARS = 1_000


def _new_id() -> str:
    return uuid.uuid4().hex


# ───────────────────── validation ─────────────────────


def validate_name(name: str) -> str:
    cleaned = (name or "").strip().lower()
    if not SERVER_NAME_RE.match(cleaned):
        raise BadRequest(
            "MCP server name must be 2-31 characters of lowercase letters, digits, "
            "'-' or '_', starting with a letter or digit."
        )
    return cleaned


def validate_transport(transport: str) -> str:
    if transport not in TRANSPORTS:
        raise BadRequest(f"transport must be one of {', '.join(TRANSPORTS)}.")
    return transport


def normalize_config(transport: str, config: Any) -> dict[str, Any]:
    """Keep only the keys the given transport uses, as strings.

    Unknown keys are dropped rather than rejected: the config is opaque to everything
    but `app.mcp.manager`, and silently storing a typo'd key would make a server that
    looks configured and never connects.
    """
    raw = config if isinstance(config, dict) else {}
    if transport == "stdio":
        command = str(raw.get("command") or "").strip()
        if not command:
            raise BadRequest("A stdio MCP server needs a 'command'.")
        args_raw = raw.get("args") or []
        if not isinstance(args_raw, list):
            raise BadRequest("'args' must be a list of strings.")
        env_raw = raw.get("env") or {}
        if not isinstance(env_raw, dict):
            raise BadRequest("'env' must be an object of string values.")
        return {
            "command": command,
            "args": [str(a) for a in args_raw],
            "env": {str(k): str(v) for k, v in env_raw.items() if v is not None},
        }

    url = str(raw.get("url") or "").strip()
    if not url:
        raise BadRequest("An http MCP server needs a 'url'.")
    if not url.startswith(("http://", "https://")):
        raise BadRequest("'url' must be an http(s) URL.")
    headers_raw = raw.get("headers") or {}
    if not isinstance(headers_raw, dict):
        raise BadRequest("'headers' must be an object of string values.")
    return {
        "url": url,
        "headers": {str(k): str(v) for k, v in headers_raw.items() if v is not None},
    }


# ───────────────────── encryption ─────────────────────


def _encrypt_config(config: dict[str, Any]) -> dict[str, str]:
    blob = encrypt(json.dumps(config, separators=(",", ":"), default=str))
    return {"ciphertext": blob["ct"], "iv": blob["iv"]}


def decrypt_config(server: McpServer) -> dict[str, Any]:
    """The server's connection config in the clear. `{}` when it cannot be read.

    A blob written under a different `ENCRYPTION_KEY` is unreadable, which must surface
    as "this server does not work" rather than a 500 from every catalog build.
    """
    blob = server.config_enc or {}
    if not isinstance(blob, dict) or not blob.get("ciphertext") or not blob.get("iv"):
        return {}
    try:
        parsed = json.loads(decrypt(blob["iv"], blob["ciphertext"]))
    except Exception:  # noqa: BLE001
        log.warning("mcp_config_decrypt_failed", server=server.name, exc_info=True)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def server_config(server: McpServer) -> McpServerConfig:
    """The decrypted `McpServerConfig` `app.mcp.manager` connects with."""
    return McpServerConfig(
        name=server.name,
        transport=server.transport,  # type: ignore[arg-type]
        config=decrypt_config(server),
        allow_private_network=bool(server.allow_private_network),
    )


# ───────────────────── reads ─────────────────────


async def list_servers(session: AsyncSession, *, enabled_only: bool = False) -> list[McpServer]:
    stmt = select(McpServer).order_by(McpServer.name)
    if enabled_only:
        stmt = stmt.where(McpServer.enabled.is_(True))
    return list((await session.execute(stmt)).scalars())


async def get_server(session: AsyncSession, server_id: str) -> McpServer | None:
    return (
        await session.execute(select(McpServer).where(McpServer.id == server_id))
    ).scalar_one_or_none()


async def get_server_by_name(session: AsyncSession, name: str) -> McpServer | None:
    return (
        await session.execute(select(McpServer).where(McpServer.name == name))
    ).scalar_one_or_none()


def cached_tools(server: McpServer) -> list[McpToolInfo]:
    """The last synced tool listing, skipping anything unusable."""
    raw = server.cached_tools if isinstance(server.cached_tools, list) else []
    tools = [McpToolInfo.from_dict(entry) for entry in raw]
    return [t for t in tools if t is not None]


def is_connected(server: McpServer) -> bool:
    """Whether the server is usable right now: enabled, synced, and not in error."""
    return bool(server.enabled) and bool(cached_tools(server)) and not server.last_error


# ───────────────────── writes ─────────────────────


async def create_server(
    session: AsyncSession,
    *,
    name: str,
    transport: str,
    config: Any,
    allow_private_network: bool = False,
    enabled: bool = True,
) -> McpServer:
    clean_name = validate_name(name)
    clean_transport = validate_transport(transport)
    clean_config = normalize_config(clean_transport, config)
    if await get_server_by_name(session, clean_name) is not None:
        raise Conflict(f"An MCP server named '{clean_name}' already exists.")
    server = McpServer(
        id=_new_id(),
        name=clean_name,
        transport=clean_transport,
        config_enc=_encrypt_config(clean_config),
        enabled=enabled,
        allow_private_network=bool(allow_private_network),
        cached_tools=[],
        last_error=None,
    )
    session.add(server)
    await session.flush()
    return server


async def update_server(
    session: AsyncSession,
    server: McpServer,
    *,
    name: str | None = None,
    transport: str | None = None,
    config: Any | None = None,
    allow_private_network: bool | None = None,
    enabled: bool | None = None,
) -> McpServer:
    """Partial update. Changing the transport requires a config for the new transport."""
    if name is not None:
        clean_name = validate_name(name)
        if clean_name != server.name:
            existing = await get_server_by_name(session, clean_name)
            if existing is not None and existing.id != server.id:
                raise Conflict(f"An MCP server named '{clean_name}' already exists.")
            # The old connection is keyed by the old name, and its tool ids embedded that
            # name too — drop both rather than leave a connection nothing can reach.
            await get_manager().disconnect(server.name)
            server.name = clean_name
    if transport is not None:
        clean_transport = validate_transport(transport)
        if clean_transport != server.transport and config is None:
            raise BadRequest(
                f"Changing the transport to '{clean_transport}' needs a matching config."
            )
        server.transport = clean_transport
    if config is not None:
        server.config_enc = _encrypt_config(normalize_config(server.transport, config))
    if allow_private_network is not None:
        server.allow_private_network = bool(allow_private_network)
    if enabled is not None:
        server.enabled = bool(enabled)
    server.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return server


async def delete_server(session: AsyncSession, server: McpServer) -> None:
    await get_manager().disconnect(server.name)
    await session.delete(server)
    await session.flush()


async def set_cached_tools(
    session: AsyncSession,
    server: McpServer,
    tools: list[McpToolInfo] | None,
    *,
    error: str | None = None,
) -> McpServer:
    """Record the outcome of a sync.

    A failed sync keeps the previous listing (passing `tools=None`): losing every action
    an automation refers to because a server was briefly down would turn every document
    using it invalid.
    """
    if tools is not None:
        server.cached_tools = [t.to_dict() for t in tools]
    server.last_error = error[:MAX_ERROR_CHARS] if error else None
    server.last_synced_at = datetime.now(timezone.utc)
    server.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return server


async def sync_server(session: AsyncSession, server: McpServer) -> McpServer:
    """Connect, list the tools, and store them (or the error) on the row.

    Never raises: a server that cannot be reached is a registered server with a
    `last_error`, which is what the UI renders and what `is_connected` reads.
    """
    try:
        tools = await get_manager().list_tools(server_config(server), refresh=True)
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None)
        message = str(detail or exc) or type(exc).__name__
        log.warning("mcp_sync_failed", server=server.name, error=message[:200])
        return await set_cached_tools(session, server, None, error=message)
    log.info("mcp_synced", server=server.name, tools=len(tools))
    return await set_cached_tools(session, server, tools)


# ───────────────────── presentation ─────────────────────


def public_view(server: McpServer) -> dict[str, Any]:
    """Everything about a server that is safe to return over HTTP.

    Secrets are reduced to their key names: `env_names` for stdio, `header_names` for
    http. The values never leave this process (`decrypt_config` is for the manager), so
    the UI can show *that* a token is configured without ever reading it back.
    """
    config = decrypt_config(server)
    tools = cached_tools(server)
    view: dict[str, Any] = {
        "id": server.id,
        "name": server.name,
        "transport": server.transport,
        "enabled": bool(server.enabled),
        "allow_private_network": bool(server.allow_private_network),
        "connected": is_connected(server),
        "tool_count": len(tools),
        "tools": [{"name": t.name, "description": t.description} for t in tools],
        "last_error": server.last_error,
        "last_synced_at": server.last_synced_at,
        "command": None,
        "args": [],
        "env_names": [],
        "url": None,
        "header_names": [],
    }
    if server.transport == "stdio":
        view["command"] = config.get("command")
        args = config.get("args")
        view["args"] = [str(a) for a in args] if isinstance(args, list) else []
        env = config.get("env")
        view["env_names"] = sorted(env) if isinstance(env, dict) else []
    else:
        view["url"] = config.get("url")
        headers = config.get("headers")
        view["header_names"] = sorted(headers) if isinstance(headers, dict) else []
    return view
