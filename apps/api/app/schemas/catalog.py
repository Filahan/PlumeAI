"""Response schemas for `GET /tools` — the merged integration + builtin + MCP catalog."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import APISchema


class CatalogActionSchema(APISchema):
    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]
    output_description: str = ""
    output_schema: dict[str, Any] | None = None


class CatalogIntegrationSchema(APISchema):
    name: str
    label: str
    description: str
    logo_url: str = ""
    connect_mode: Literal["oauth", "config"] = "oauth"
    setup_url: str = ""
    credentials_namespace: str | None = None
    credentials_fields: list[dict[str, Any]] = Field(default_factory=list)
    setup: dict[str, Any] = Field(default_factory=dict)
    connected: bool = False
    actions: list[CatalogActionSchema] = Field(default_factory=list)


class CatalogMcpServerSchema(APISchema):
    """One registered MCP server. Serialized as `mcpServers[]` on `GET /tools`.

    Connection details are deliberately absent — the command, URL and the names of the
    secrets it carries live on `GET /mcp/servers` (see `app.schemas.mcp`), which is the
    endpoint the settings UI reads; this one only has to say which actions exist and
    whether they can be run.
    """

    name: str
    transport: str
    enabled: bool = True
    connected: bool = False
    last_error: str | None = None
    actions: list[CatalogActionSchema] = Field(default_factory=list)


class CatalogResponse(APISchema):
    integrations: list[CatalogIntegrationSchema]
    builtin_actions: list[CatalogActionSchema]
    mcp_servers: list[CatalogMcpServerSchema] = Field(default_factory=list)
