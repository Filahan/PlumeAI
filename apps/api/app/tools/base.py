"""Shared types + helpers for tools (built-in and integration registry)."""

from __future__ import annotations

import asyncio
import copy
import ipaddress
import socket
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.errors import ToolError

log = structlog.get_logger("app.tools")

MAX_RESULT_CHARS = 12_000
TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) PlumeAI-Automations/1.0"
)


@dataclass
class ToolResult:
    """What every tool returns. Truncation is the tool's responsibility (cap to MAX_RESULT_CHARS).

    `retryable` only means anything when `ok` is False, and it answers one question for the
    automation executor: could another attempt do better? A timeout or a 502 says yes; a
    request the tool *rejected* — an unknown tool name, a disconnected integration, a URL
    pointing at a private host — says no, and retrying it would only delay the failure the
    author has to see. Defaults to True, so a tool that doesn't think about it keeps the
    forgiving behavior.
    """

    ok: bool
    content: str
    data: Any | None = None
    retryable: bool = True


class ToolFn(Protocol):
    """Async signature shared by all tool implementations."""

    async def __call__(self, args: dict[str, Any]) -> ToolResult: ...


# ───────────────────── catalog / display metadata ─────────────────────
#
# Lives here (the lower layer) rather than in `app.integrations.base` so that
# `app.tools.builtin` — which sits below `app.integrations` in the dependency graph —
# can describe its own actions without importing from `app.integrations`.

BUILTIN_INTEGRATION = "builtin"


@dataclass(frozen=True)
class CatalogAction:
    """Catalog-ready descriptor for one action (tool function), whether it comes from
    a first-party integration or a builtin tool. Returned by `describe_action`,
    `Integration.describe_actions`, and `describe_builtin_actions`.

    Structurally compatible (by duck typing) with the `ActionMeta` dataclass
    `app.services.documents` expects from its `ActionCatalog` protocol: same
    `name, integration, label, description, input_schema` fields, plus two extra
    display-only fields that module never reads.
    """

    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]
    output_description: str = ""
    output_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionDisplayMeta:
    """Hand-written, human-facing metadata for one action. Keyed by function name in
    `Integration.action_meta` / `BUILTIN_ACTION_META`. Falls back to a humanized
    function name when an action has no entry (see `_humanize`)."""

    label: str
    output_description: str = ""
    output_schema: dict[str, Any] | None = None


def _humanize(name: str) -> str:
    """Fallback label for an action with no `ActionDisplayMeta` entry, e.g.
    `gmail_search` → `Gmail search`."""
    return name.replace("_", " ").capitalize()


def describe_action(
    schema: dict[str, Any], integration: str, action_meta: dict[str, ActionDisplayMeta]
) -> CatalogAction:
    """Turn one OpenAI function-calling schema into a `CatalogAction`. Shared by
    `Integration.describe_actions` and `describe_builtin_actions` so both produce the
    exact same shape.

    `input_schema` is deep-copied so the returned catalog entry never shares a mutable
    reference with the live schema handed to the LLM.
    """

    fn = schema["function"]
    name = fn["name"]
    meta = action_meta.get(name)
    return CatalogAction(
        name=name,
        integration=integration,
        label=meta.label if meta else _humanize(name),
        description=fn.get("description", ""),
        input_schema=copy.deepcopy(fn.get("parameters", {})),
        output_description=meta.output_description if meta else "",
        output_schema=meta.output_schema if meta else None,
    )


def cap(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "\n…[truncated]"


def safe_json_args(raw: str) -> dict[str, Any]:
    """Parse JSON-stringified tool arguments. Returns {} on malformed input rather than raising."""
    import json

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ───────────────────── SSRF guard ─────────────────────
#
# Every rejection here is about the URL itself, so it is permanent: `extra={"retryable":
# False}` is how `app.tools.registry` learns not to hand the automation executor something
# worth retrying. Passed through `extra` rather than a new `ToolError` field so the error
# hierarchy (and the HTTP problem-details shape it feeds) stays as it was.
_PERMANENT = {"retryable": False}

_PRIVATE_HOSTS = {"localhost"}
_PRIVATE_SUFFIXES = (".local", ".internal")


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → treat as private (deny)
    # `is_global` excludes private, loopback, link-local, multicast, reserved, etc.
    return not addr.is_global


async def _resolve_addresses(host: str) -> list[str]:
    """Async DNS lookup. Returns the unique IP strings resolved for the host."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ToolError(f"Could not resolve host: {host}") from exc
    return list({info[4][0] for info in infos})


async def assert_public_url(raw_url: str) -> str:
    """Validate that `raw_url` is an http(s) URL pointing at a public host. Returns the URL.

    Raises `ToolError` for any URL pointing at private/loopback addresses or hosts that
    resolve to non-globally-routable IPs. Mirrors the Node `assertPublicUrl` behavior.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(raw_url)
    except ValueError as exc:
        raise ToolError(f"Invalid URL: {raw_url}", extra=_PERMANENT) from exc

    if parsed.scheme not in ("http", "https"):
        raise ToolError(
            f"Only http(s) URLs are allowed (got {parsed.scheme}).", extra=_PERMANENT
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ToolError("URL is missing a host.", extra=_PERMANENT)
    if host in _PRIVATE_HOSTS or host.endswith(_PRIVATE_SUFFIXES):
        raise ToolError("Requests to internal hosts are not allowed.", extra=_PERMANENT)

    # Already-an-IP shortcut
    try:
        ipaddress.ip_address(host)
        if _is_private_ip(host):
            raise ToolError(
                "Requests to private addresses are not allowed.", extra=_PERMANENT
            )
        return raw_url
    except ValueError:
        pass

    for ip in await _resolve_addresses(host):
        if _is_private_ip(ip):
            raise ToolError(
                f"Host {host} resolves to a private address; blocked.", extra=_PERMANENT
            )
    return raw_url


# ───────────────────── timeout helper ─────────────────────

async def with_timeout(
    coro: Coroutine[Any, Any, Any], seconds: int = TIMEOUT_SECONDS
) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise ToolError(f"Tool timed out after {seconds}s.") from exc


def redact_args(raw: str, max_len: int = 600) -> str:
    return raw if len(raw) <= max_len else raw[:max_len] + "…"
