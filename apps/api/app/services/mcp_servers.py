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

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.models import McpServer
from app.errors import BadRequest, Conflict
from app.mcp import McpServerConfig, McpToolInfo, assert_stdio_allowed, get_manager
from app.mcp.schemas import SERVER_NAME_RE, TRANSPORTS

log = structlog.get_logger("app.services.mcp_servers")

# `last_error` is shown in the UI, and its writer is a third-party server's error text.
MAX_ERROR_CHARS = 1_000
# A sync happens inside a request (`POST /mcp/servers`, `…/refresh`), so it gets the same
# budget as `POST /mcp/servers/test` rather than the manager's longer internal timeouts.
SYNC_TIMEOUT = 20


def _new_id() -> str:
    return uuid.uuid4().hex


# ───────────────────── masking ─────────────────────
#
# The encrypted config keeps secrets out of the database, but two of them leak through
# *shapes* the UI wants to show: an argv like `mcp-server --api-key=sk-…`, and a URL with
# the token in its query string. Both are masked on the way out, and the same masking runs
# over `last_error` before it is stored — a connection error quotes the URL it failed on.

MASK = "***"
_SECRET_ARG = re.compile(
    r"^(?P<flag>-{0,2}[\w.-]*(?:key|token|secret|password|passwd|pass|auth|credential)"
    r"[\w.-]*)=(?P<value>.+)$",
    re.IGNORECASE,
)
_SECRET_FLAG = re.compile(
    r"^-{1,2}[\w.-]*(?:key|token|secret|password|passwd|pass|auth|credential)[\w.-]*$",
    re.IGNORECASE,
)
_URL_IN_TEXT = re.compile(r"(https?://[^\s'\"]+)")


def mask_url(url: str) -> str:
    """`https://host/mcp?token=abc` → `https://host/mcp?token=***`.

    Query *names* survive (like `header_names` does); values never do. Userinfo
    (`https://user:pw@host`) is dropped entirely.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    netloc = parts.netloc.rpartition("@")[2] if "@" in parts.netloc else parts.netloc
    query = parts.query
    if query:
        query = "&".join(
            f"{pair.partition('=')[0]}={MASK}" if "=" in pair else pair
            for pair in query.split("&")
        )
    fragment = MASK if parts.fragment else ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))


def mask_args(args: list[str]) -> list[str]:
    """Mask values that look like credentials: `--api-key=sk-…`, `--token sk-…`."""
    masked: list[str] = []
    mask_next = False
    for arg in args:
        if mask_next:
            masked.append(MASK)
            mask_next = False
            continue
        hit = _SECRET_ARG.match(arg)
        if hit:
            masked.append(f"{hit.group('flag')}={MASK}")
            continue
        if _SECRET_FLAG.match(arg):
            mask_next = True
        masked.append(arg)
    return masked


def mask_text(text: str) -> str:
    """Mask every URL inside free text — used on error messages before they are stored."""

    def replace(match: re.Match[str]) -> str:
        url = match.group(1)
        # Sentence punctuation right after a URL is not part of it.
        trailing = ""
        while url and url[-1] in ".,;:!?)]}\'\"":
            trailing = url[-1] + trailing
            url = url[:-1]
        return mask_url(url) + trailing

    return _URL_IN_TEXT.sub(replace, text)


# ───────────────────── validation ─────────────────────


def validate_name(name: str) -> str:
    """Check the slug. Deliberately does *not* rewrite it.

    `app.schemas.mcp` carries the same pattern, so a name that needs fixing is a 422 with
    the field named, not a silently different server than the one the user asked for —
    and the name is not a cosmetic label: it is half of every tool id.
    """
    if not SERVER_NAME_RE.match(name or ""):
        raise BadRequest(
            "MCP server name must be 2-31 characters of lowercase letters, digits, "
            "'-' or '_', starting with a letter or digit."
        )
    return name


def validate_transport(transport: str) -> str:
    """Check the transport is one we speak, and that this deployment allows it.

    `assert_stdio_allowed` is the `MCP_ALLOW_STDIO` gate: a stdio server is a command the
    API container runs, and the API has no login in front of it (see `docs/security.md`).
    """
    if transport not in TRANSPORTS:
        raise BadRequest(f"transport must be one of {', '.join(TRANSPORTS)}.")
    assert_stdio_allowed(transport)
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
    # Editing a stdio server is as good as registering one (the command is what changes),
    # so the `MCP_ALLOW_STDIO` gate applies to the transport this update lands on.
    assert_stdio_allowed(transport or server.transport)
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
    server.last_error = mask_text(error)[:MAX_ERROR_CHARS] if error else None
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
        tools = await asyncio.wait_for(
            get_manager().list_tools(server_config(server), refresh=True), SYNC_TIMEOUT
        )
    except asyncio.TimeoutError:
        return await set_cached_tools(
            session, server, None, error=f"Syncing timed out after {SYNC_TIMEOUT}s."
        )
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
        view["args"] = mask_args([str(a) for a in args]) if isinstance(args, list) else []
        env = config.get("env")
        view["env_names"] = sorted(env) if isinstance(env, dict) else []
    else:
        url = config.get("url")
        view["url"] = mask_url(str(url)) if url else None
        headers = config.get("headers")
        view["header_names"] = sorted(headers) if isinstance(headers, dict) else []
    return view
