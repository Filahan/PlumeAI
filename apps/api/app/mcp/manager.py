"""The MCP client: one live connection per registered server, shared by every caller.

**Why a per-connection worker task.** The Python MCP SDK's transports are anyio context
managers that open a task group internally (a subprocess plus its two pumps for stdio, a
POST writer and an SSE reader for Streamable HTTP). A task group belongs to the task that
entered it, so a connection cannot be opened inside one request and closed inside another
— anyio raises if a cancel scope is exited from a different task. Each connection
therefore lives in its own asyncio task that opens the client, serves jobs off a queue
until told to stop, and closes the client itself. Callers hand in a coroutine factory and
await a future; nothing but the worker ever touches the SDK session.

**Security.** The two transports have very different trust profiles, and both are
operator-configured (PlumeAI is single-tenant and single-user — see `app.auth`):

- `http`: the URL is checked with `app.tools.base.assert_public_url` before connecting, so
  a registered server cannot be used to reach the Docker network, the metadata service or
  anything else the container can see but the internet cannot. `allow_private_network=True`
  skips that check, which is what makes a `http://host.docker.internal:3000/mcp` server on
  the operator's own machine usable — and is exactly why it is opt-in per server.
- `stdio`: the command runs **as a subprocess of the API container**, with the container's
  environment plus whatever `env` the server carries. There is no sandbox: registering a
  stdio server is equivalent to running that command on the server. The image ships `uv`
  and `uvx` but no node/npx, so `uvx mcp-server-time` works out of the box while
  `npx -y @foo/mcp-server` does not.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp_types import CallToolResult, PaginatedRequestParams

from app.errors import AppError, ToolError
from app.mcp.schemas import McpServerConfig, McpToolInfo
from app.tools.base import ToolResult, assert_public_url, cap
from app.utils import LoopLocal

log = structlog.get_logger("app.mcp")

# A tool call is a network round trip to somebody else's server; 60s is the generous
# default the automation executor's own step timeout sits on top of.
DEFAULT_CALL_TIMEOUT = 60
# Listing tools is a handshake plus one request — if that takes longer, the server is
# broken and the UI should hear about it while the user is still looking at it.
LIST_TIMEOUT = 20
# `POST /mcp/servers/test` is interactive: fail fast rather than hold the request open.
TEST_TIMEOUT = 20
# Connecting includes spawning a subprocess (stdio) or the HTTP handshake.
CONNECT_TIMEOUT = 30
# How long a graceful worker shutdown gets before the task is cancelled outright.
CLOSE_TIMEOUT = 10
# Slack on top of a job's own timeout, covering the queue wait behind a slow call.
QUEUE_GRACE = 5
# Guard against a server that paginates forever.
MAX_TOOL_PAGES = 20

_NO_CONTENT = "(the tool returned no content)"


class _ConnectionLost(Exception):
    """The worker serving this connection is gone — the job never ran, so a retry on a
    fresh connection is safe (and is what `_run_job` does, once)."""


# ───────────────────── transports ─────────────────────


@asynccontextmanager
async def _http_transport(url: str, headers: dict[str, str]) -> AsyncIterator[Any]:
    """Streamable HTTP streams, with our own httpx client so headers can be set.

    `streamable_http_client` only manages the lifetime of a client it created itself, so
    the one passed in is closed here.
    """
    http_client = create_mcp_http_client(headers=headers or None)
    async with http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            yield streams


def _str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _build_client(cfg: McpServerConfig) -> Client:
    """An un-entered `Client` for `cfg`. Raises `ToolError` on a malformed config."""
    config = cfg.config if isinstance(cfg.config, dict) else {}
    if cfg.transport == "stdio":
        command = str(config.get("command") or "").strip()
        if not command:
            raise ToolError(
                f"MCP server '{cfg.name}' has no command to run.",
                extra={"retryable": False},
            )
        raw_args = config.get("args")
        args = [str(a) for a in raw_args] if isinstance(raw_args, list) else []
        return Client(
            StdioServerParameters(command=command, args=args, env=_str_map(config.get("env"))),
            read_timeout_seconds=float(DEFAULT_CALL_TIMEOUT),
        )
    url = str(config.get("url") or "").strip()
    if not url:
        raise ToolError(
            f"MCP server '{cfg.name}' has no URL.", extra={"retryable": False}
        )
    return Client(
        _http_transport(url, _str_map(config.get("headers"))),
        read_timeout_seconds=float(DEFAULT_CALL_TIMEOUT),
    )


async def _validate_config(cfg: McpServerConfig) -> None:
    """Pre-connect checks. Raises `ToolError` (permanent) when the config is refused."""
    if cfg.transport != "http":
        return
    config = cfg.config if isinstance(cfg.config, dict) else {}
    url = str(config.get("url") or "").strip()
    if not url:
        raise ToolError(f"MCP server '{cfg.name}' has no URL.", extra={"retryable": False})
    if cfg.allow_private_network:
        # Deliberately unguarded: the operator asked for a server on their own network.
        return
    await assert_public_url(url)


# ───────────────────── tool listing / call mapping ─────────────────────


async def _list_tools(client: Client) -> list[McpToolInfo]:
    """Every page of `tools/list`, flattened."""
    tools: list[McpToolInfo] = []
    cursor: str | None = None
    for _ in range(MAX_TOOL_PAGES):
        result = await client.session.list_tools(
            params=PaginatedRequestParams(cursor=cursor) if cursor else None
        )
        for tool in result.tools:
            tools.append(
                McpToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.input_schema
                    if isinstance(tool.input_schema, dict)
                    else {},
                )
            )
        cursor = result.next_cursor
        if not cursor:
            break
    return tools


def _result_to_tool_result(name: str, result: CallToolResult) -> ToolResult:
    """Map a `CallToolResult` onto PlumeAI's `ToolResult`.

    Text blocks are what the agent loop and the step runner read; `structuredContent`
    becomes `data`, which is what `{{step.output.field}}` references resolve against.
    Non-text blocks (images, resources) are counted, not inlined: the rest of the
    pipeline is text/JSON only.
    """
    texts: list[str] = []
    other = 0
    for block in result.content or ():
        text = getattr(block, "text", None)
        if getattr(block, "type", None) == "text" and isinstance(text, str):
            texts.append(text)
        else:
            other += 1
    content = "\n".join(t for t in texts if t)
    if other:
        suffix = f"[{other} non-text content block(s) omitted]"
        content = f"{content}\n{suffix}" if content else suffix
    if not content:
        content = _NO_CONTENT
    if result.is_error:
        # The server rejected or failed the call. Whether another attempt could do better
        # is not knowable from here (an MCP error carries no machine-readable kind), and
        # the executor's retry budget is small and bounded — so it stays retryable, the
        # same default `ToolResult` itself uses.
        return ToolResult(ok=False, content=cap(f"MCP tool {name} failed: {content}"))
    return ToolResult(
        ok=True, content=cap(content), data=result.structured_content
    )


def _error_text(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    text = str(detail or exc) or type(exc).__name__
    return text[:600]


# ───────────────────── one connection ─────────────────────

_Job = tuple["Callable[[Client], Awaitable[Any]]", float, "asyncio.Future[Any]"]


class _Connection:
    """A live client session plus the task that owns it."""

    def __init__(self, cfg: McpServerConfig) -> None:
        self.cfg = cfg
        self.fingerprint = cfg.fingerprint
        self._jobs: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._alive = False

    @property
    def alive(self) -> bool:
        return self._alive and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Open the connection, or raise whatever stopped it from opening."""
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._serve(ready), name=f"mcp-{self.cfg.name}")
        try:
            await asyncio.wait_for(asyncio.shield(ready), CONNECT_TIMEOUT)
        except asyncio.TimeoutError as exc:
            # Cancel the handshake future first: `_serve` only reports a late failure
            # through it while it is still pending, and nobody is reading it any more.
            ready.cancel()
            await self.close()
            raise ToolError(
                f"Connecting to MCP server '{self.cfg.name}' timed out "
                f"after {CONNECT_TIMEOUT}s."
            ) from exc
        except BaseException:
            await self.close()
            raise
        self._alive = True

    async def _serve(self, ready: asyncio.Future[None]) -> None:
        """Own the client for its whole lifetime: open, serve jobs, close."""
        try:
            async with _build_client(self.cfg) as client:
                if not ready.done():
                    ready.set_result(None)
                while True:
                    job = await self._jobs.get()
                    if job is None:
                        return
                    fn, timeout, future = job
                    if future.done():  # the caller gave up before we got here
                        continue
                    try:
                        value = await asyncio.wait_for(fn(client), timeout)
                    except asyncio.CancelledError:
                        if not future.done():
                            future.set_exception(_ConnectionLost("connection closed"))
                        raise
                    except BaseException as exc:  # noqa: BLE001 — relayed to the caller
                        if not future.done():
                            future.set_exception(exc)
                    else:
                        if not future.done():
                            future.set_result(value)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc)
            else:
                log.warning(
                    "mcp_connection_failed", server=self.cfg.name, error=_error_text(exc)
                )
        finally:
            self._alive = False
            self._fail_pending()

    def _fail_pending(self) -> None:
        """Nobody is going to serve the queue any more — say so instead of hanging."""
        while True:
            try:
                job = self._jobs.get_nowait()
            except asyncio.QueueEmpty:
                return
            if job is None:
                continue
            _, _, future = job
            if not future.done():
                future.set_exception(_ConnectionLost("connection closed"))

    async def call(self, fn: Callable[[Client], Awaitable[Any]], timeout: float) -> Any:
        """Run `fn` against the live session, from the worker task."""
        if not self.alive:
            raise _ConnectionLost("connection closed")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._jobs.put_nowait((fn, timeout, future))
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout + QUEUE_GRACE)
        except asyncio.TimeoutError as exc:
            future.cancel()
            raise ToolError(
                f"MCP server '{self.cfg.name}' did not answer within {timeout:.0f}s."
            ) from exc

    async def close(self) -> None:
        """Stop the worker, which closes the session and reaps the subprocess."""
        self._alive = False
        task = self._task
        if task is None or task.done():
            return
        self._jobs.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(task), CLOSE_TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
        except BaseException:  # noqa: BLE001 — the worker's own failure is already logged
            pass
        with contextlib.suppress(BaseException):
            await task


# ───────────────────── the manager ─────────────────────


class McpManager:
    """Connection pool keyed by server name. One instance per event loop."""

    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # `name → (fingerprint, tools)`: the listing of a connection we already have, so
        # repeated catalog/registry reads in one process don't re-ask the server.
        self._tools: dict[str, tuple[str, list[McpToolInfo]]] = {}

    def _lock(self, name: str) -> asyncio.Lock:
        lock = self._locks.get(name)
        if lock is None:
            lock = self._locks[name] = asyncio.Lock()
        return lock

    def connected_names(self) -> list[str]:
        return sorted(name for name, conn in self._connections.items() if conn.alive)

    async def _connection(self, cfg: McpServerConfig, *, reconnect: bool = False) -> _Connection:
        """The live connection for `cfg`, opening (or replacing) it as needed."""
        async with self._lock(cfg.name):
            conn = self._connections.get(cfg.name)
            if conn is not None and (
                reconnect or not conn.alive or conn.fingerprint != cfg.fingerprint
            ):
                self._connections.pop(cfg.name, None)
                self._tools.pop(cfg.name, None)
                await conn.close()
                conn = None
            if conn is None:
                await _validate_config(cfg)
                conn = _Connection(cfg)
                try:
                    await conn.start()
                except AppError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise ToolError(
                        f"Could not connect to MCP server '{cfg.name}': {_error_text(exc)}"
                    ) from exc
                self._connections[cfg.name] = conn
                log.info("mcp_connected", server=cfg.name, transport=cfg.transport)
            return conn

    async def _run_job(
        self, cfg: McpServerConfig, fn: Callable[[Client], Awaitable[Any]], timeout: float
    ) -> Any:
        """Run `fn` on `cfg`'s connection, reconnecting once if the connection is gone.

        A stdio server's process can exit (and an HTTP session can be dropped) between
        two calls; the first attempt is how we find out, so one silent reconnect is worth
        more than an error the user has to react to.
        """
        for attempt in (0, 1):
            conn = await self._connection(cfg, reconnect=attempt == 1)
            try:
                return await conn.call(fn, timeout)
            except _ConnectionLost:
                if attempt:
                    raise ToolError(
                        f"Lost the connection to MCP server '{cfg.name}'."
                    ) from None
                log.info("mcp_reconnecting", server=cfg.name)
        raise AssertionError("unreachable")  # pragma: no cover

    async def list_tools(
        self, cfg: McpServerConfig, *, refresh: bool = False
    ) -> list[McpToolInfo]:
        """The server's tools. Cached per connection unless `refresh` is True.

        The durable cache is `mcp_servers.cached_tools` in the database, written by
        `app.services.mcp_servers.sync_server` from this listing — the catalog and the
        tool registry read *that*, never this, so building a catalog never touches the
        network.
        """
        cached = self._tools.get(cfg.name)
        if not refresh and cached is not None and cached[0] == cfg.fingerprint:
            return cached[1]
        tools = await self._run_job(cfg, _list_tools, LIST_TIMEOUT)
        self._tools[cfg.name] = (cfg.fingerprint, tools)
        return tools

    async def call_tool(
        self,
        cfg: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = DEFAULT_CALL_TIMEOUT,
    ) -> ToolResult:
        """Call one tool. Connection/config failures raise `ToolError`; a failure the
        *server* reports comes back as `ToolResult(ok=False)`."""

        async def job(client: Client) -> CallToolResult:
            return await client.call_tool(tool_name, arguments or {})

        result = await self._run_job(cfg, job, timeout)
        return _result_to_tool_result(tool_name, result)

    async def disconnect(self, name: str) -> None:
        """Close the connection to `name`, if any. The next use reconnects."""
        async with self._lock(name):
            conn = self._connections.pop(name, None)
            self._tools.pop(name, None)
        if conn is not None:
            await conn.close()
            log.info("mcp_disconnected", server=name)

    async def close_all(self) -> None:
        """Close every connection — called from the app's lifespan shutdown."""
        for name in list(self._connections):
            with contextlib.suppress(Exception):
                await self.disconnect(name)


_MANAGER: LoopLocal[McpManager] = LoopLocal(McpManager)


def get_manager() -> McpManager:
    """The per-event-loop manager instance.

    Keyed by loop (rather than a plain module global) for the same reason
    `app.utils.LoopLocal` exists: the connections hold `asyncio` primitives bound to the
    loop that created them, and the test suite gives every test its own loop.
    """
    return _MANAGER.get()


async def close_all() -> None:
    await get_manager().close_all()


async def test_server(cfg: McpServerConfig, *, timeout: float = TEST_TIMEOUT) -> dict[str, Any]:
    """Connect, list tools, disconnect — without touching the pool or the database.

    Returns `{"ok": True, "tools": [...]}` or `{"ok": False, "error": "..."}`; it never
    raises, because both outcomes are a 200 for `POST /mcp/servers/test`.
    """

    async def probe() -> list[McpToolInfo]:
        async with _build_client(cfg) as client:
            return await _list_tools(client)

    try:
        await _validate_config(cfg)
        tools = await asyncio.wait_for(probe(), timeout)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": f"Connecting to the MCP server timed out after {timeout:.0f}s.",
        }
    except Exception as exc:  # noqa: BLE001 — every failure is a result, not a raise
        log.info("mcp_test_failed", server=cfg.name, error=_error_text(exc))
        return {"ok": False, "error": _error_text(exc)}
    return {"ok": True, "tools": [t.to_dict() for t in tools]}
