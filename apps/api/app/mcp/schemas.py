"""Pure value types and naming rules for MCP servers and their tools.

No I/O, no SDK imports: `app.mcp.manager` does the talking, this module only describes
*what* is being talked to (`McpServerConfig`), *what came back* (`McpToolInfo`) and how an
MCP tool is named once it enters PlumeAI's flat, single-namespace tool space
(`tool_id` / `parse_tool_id` / `to_openai_schema`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

Transport = Literal["stdio", "http"]

TRANSPORTS: tuple[str, ...] = ("stdio", "http")

# Server names are slugs: they become part of a tool id and of an integration name
# (`mcp:<server>`), both of which travel through JSON schemas and LLM tool calls.
SERVER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")

# One namespace for every tool the agent can call, so an MCP tool needs a name that
# cannot collide with a builtin or an integration action: `mcp__<server>__<tool>`.
TOOL_ID_PREFIX = "mcp__"
TOOL_ID_SEPARATOR = "__"

# OpenAI (and Anthropic) only accept `^[a-zA-Z0-9_-]{1,64}$` for a function name, while
# an MCP server may name a tool anything at all — hence the sanitize + truncate below.
_ILLEGAL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
MAX_TOOL_ID_CHARS = 64

# Sanitizing and truncating is lossy, so the exact `(server, tool)` pair behind every id
# handed out is remembered here: `parse_tool_id` consults it before falling back to
# splitting the id, which is the only way a tool called `do__thing` (or one whose name had
# to be shortened) can still be dispatched. Bounded by the number of distinct tools the
# process has seen.
_REVERSE_IDS: dict[str, tuple[str, str]] = {}


@dataclass(frozen=True)
class McpToolInfo:
    """One tool as advertised by an MCP server, in the shape we cache in the database."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(self.input_schema),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> McpToolInfo | None:
        """Rebuild from a cached JSONB entry. Returns None for anything unusable.

        Defensive because the row is data the *server* supplied: a cached listing written
        by an older build (or hand-edited) must not break catalog assembly.
        """
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None
        description = raw.get("description")
        schema = raw.get("input_schema")
        if not isinstance(schema, dict):
            schema = raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else {}
        return cls(
            name=name,
            description=description if isinstance(description, str) else "",
            input_schema=schema,
        )


@dataclass(frozen=True)
class McpServerConfig:
    """Everything needed to open one connection, with secrets already decrypted.

    `config` is the transport-specific half: `{command, args, env}` for stdio,
    `{url, headers}` for Streamable HTTP. Built by
    `app.services.mcp_servers.server_config` from a `McpServer` row; never persisted.
    """

    name: str
    transport: Transport
    config: dict[str, Any] = field(default_factory=dict)
    allow_private_network: bool = False

    @property
    def fingerprint(self) -> str:
        """Stable hash of the connection parameters.

        The manager keys a live connection by it, so editing a server's command, URL or
        headers replaces the connection instead of silently reusing the old process.
        """
        payload = json.dumps(
            [self.name, self.transport, self.config, self.allow_private_network],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ───────────────────── tool naming ─────────────────────


def integration_name(server_name: str) -> str:
    """The catalog integration an MCP server's actions belong to: `mcp:<server>`."""
    return f"mcp:{server_name}"


def parse_integration_name(integration: str) -> str | None:
    """`mcp:<server>` → `<server>`; None for anything else."""
    prefix = "mcp:"
    if not integration.startswith(prefix):
        return None
    return integration[len(prefix) :] or None


def _sanitize(part: str) -> str:
    return _ILLEGAL_NAME_CHARS.sub("_", part)


def tool_id(server_name: str, tool_name: str) -> str:
    """`mcp__<server>__<tool>`, sanitized and truncated to a legal function name.

    Registers the result in `_REVERSE_IDS` so `parse_tool_id` can recover the original
    names even when sanitizing or truncating changed them.
    """
    server = _sanitize(server_name)
    tool = _sanitize(tool_name)
    base = f"{TOOL_ID_PREFIX}{server}{TOOL_ID_SEPARATOR}"
    room = MAX_TOOL_ID_CHARS - len(base)
    if room < 8:
        # Pathologically long server name — shorten it so the tool still gets 8 chars.
        keep = MAX_TOOL_ID_CHARS - len(TOOL_ID_PREFIX) - len(TOOL_ID_SEPARATOR) - 8
        server = server[: max(1, keep)]
        base = f"{TOOL_ID_PREFIX}{server}{TOOL_ID_SEPARATOR}"
        room = MAX_TOOL_ID_CHARS - len(base)
    if len(tool) > room:
        digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:6]
        tool = f"{tool[: room - 7]}_{digest}"
    identifier = base + tool
    _REVERSE_IDS[identifier] = (server_name, tool_name)
    return identifier


def is_mcp_tool_id(name: str) -> bool:
    return name.startswith(TOOL_ID_PREFIX)


def parse_tool_id(identifier: str) -> tuple[str, str] | None:
    """`mcp__<server>__<tool>` → `(server, tool)`; None when it isn't an MCP tool id.

    The `_REVERSE_IDS` hit is the accurate answer; the split is the fallback for an id
    minted by a previous process (a document saved yesterday, replayed today).
    """
    known = _REVERSE_IDS.get(identifier)
    if known is not None:
        return known
    if not is_mcp_tool_id(identifier):
        return None
    server, separator, tool = identifier[len(TOOL_ID_PREFIX) :].partition(TOOL_ID_SEPARATOR)
    if not separator or not server or not tool:
        return None
    return server, tool


def humanize_tool(tool_name: str) -> str:
    """`create_issue` → `Create issue`; used as the catalog action label."""
    cleaned = tool_name.replace("-", " ").replace("_", " ").strip()
    return cleaned.capitalize() if cleaned else tool_name


def to_openai_schema(server_name: str, tool: McpToolInfo) -> dict[str, Any]:
    """One MCP tool as an OpenAI function-calling schema.

    The server prefix stays in the description as well as the name: the model sees dozens
    of tools at once, and `[github] Create an issue` is what tells it which one it is
    reaching for.
    """
    parameters = copy.deepcopy(tool.input_schema) if isinstance(tool.input_schema, dict) else {}
    if not parameters:
        parameters = {"type": "object", "properties": {}}
    description = tool.description or tool.name
    return {
        "type": "function",
        "function": {
            "name": tool_id(server_name, tool.name),
            "description": f"[{server_name}] {description}",
            "parameters": parameters,
        },
    }
