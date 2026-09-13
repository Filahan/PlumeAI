"""Request/response schemas for `/mcp` — registering MCP servers and syncing their tools.

The asymmetry between request and response is the point: a request carries the secrets
(`config.env`, `config.headers`), a response never does. `McpServerPayload` is built from
`app.services.mcp_servers.public_view`, which reduces them to `envNames` / `headerNames`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import APISchema

Transport = Literal["stdio", "http"]

# Mirrors `app.mcp.schemas.SERVER_NAME_RE`: the name becomes part of every tool id the
# model sees (`mcp__<name>__<tool>`) and of the `mcp:<name>` integration in a document.
NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,30}$"


class McpToolPayload(APISchema):
    name: str
    description: str = ""


class McpServerPayload(APISchema):
    """One registered server, as the settings UI sees it. Never carries a secret value."""

    id: str
    name: str
    transport: Transport
    enabled: bool = True
    allow_private_network: bool = False
    connected: bool = False
    tool_count: int = 0
    tools: list[McpToolPayload] = Field(default_factory=list)
    last_error: str | None = None
    last_synced_at: int | None = None
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env_names: list[str] = Field(default_factory=list)
    # http
    url: str | None = None
    header_names: list[str] = Field(default_factory=list)


class McpServerListResponse(APISchema):
    servers: list[McpServerPayload] = Field(default_factory=list)


class CreateMcpServerRequest(APISchema):
    """`config` is `{command, args?, env?}` for stdio, `{url, headers?}` for http.

    Left as a free-form object rather than a union so the error message comes from
    `app.services.mcp_servers.normalize_config`, which knows *why* a config is wrong
    ("A stdio MCP server needs a 'command'") instead of a generic discriminator failure.
    """

    name: str = Field(pattern=NAME_PATTERN)
    transport: Transport
    config: dict[str, Any] = Field(default_factory=dict)
    allow_private_network: bool = False
    enabled: bool = True


class UpdateMcpServerRequest(APISchema):
    """Partial update: every field that is left out keeps its stored value."""

    name: str | None = Field(default=None, pattern=NAME_PATTERN)
    transport: Transport | None = None
    config: dict[str, Any] | None = None
    allow_private_network: bool | None = None
    enabled: bool | None = None


class PatchMcpServerRequest(APISchema):
    enabled: bool


class TestMcpServerRequest(APISchema):
    transport: Transport
    config: dict[str, Any] = Field(default_factory=dict)
    allow_private_network: bool = False


class TestMcpServerResponse(APISchema):
    ok: bool
    tools: list[McpToolPayload] = Field(default_factory=list)
    error: str | None = None
