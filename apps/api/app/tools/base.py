"""Shared types + helpers for tools (built-in and integration registry)."""

from __future__ import annotations

import asyncio
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
    """What every tool returns. Truncation is the tool's responsibility (cap to MAX_RESULT_CHARS)."""

    ok: bool
    content: str


class ToolFn(Protocol):
    """Async signature shared by all tool implementations."""

    async def __call__(self, args: dict[str, Any]) -> ToolResult: ...


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
        raise ToolError(f"Invalid URL: {raw_url}") from exc

    if parsed.scheme not in ("http", "https"):
        raise ToolError(f"Only http(s) URLs are allowed (got {parsed.scheme}).")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ToolError("URL is missing a host.")
    if host in _PRIVATE_HOSTS or host.endswith(_PRIVATE_SUFFIXES):
        raise ToolError("Requests to internal hosts are not allowed.")

    # Already-an-IP shortcut
    try:
        ipaddress.ip_address(host)
        if _is_private_ip(host):
            raise ToolError("Requests to private addresses are not allowed.")
        return raw_url
    except ValueError:
        pass

    for ip in await _resolve_addresses(host):
        if _is_private_ip(ip):
            raise ToolError(f"Host {host} resolves to a private address; blocked.")
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
