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
- `stdio`: the command runs **as a subprocess of the API container**. There is no sandbox:
  registering a stdio server is equivalent to running that command on the server, which is
  why it is gated behind `MCP_ALLOW_STDIO` (see `app.config`) and refused by default
  outside development. The child's environment is *not* the API's: the SDK passes only the
  allowlist in `mcp.client.stdio.get_default_environment()` — `HOME`, `LOGNAME`, `PATH`,
  `SHELL`, `TERM`, `USER` — plus the server's own `env`, so `ENCRYPTION_KEY`,
  `DATABASE_URL` and the provider keys never reach it. The image ships `uv` and `uvx` but
  no node/npx, so `uvx mcp-server-time` works out of the box while `npx -y @foo/mcp-server`
  does not.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import structlog
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import CONNECTION_CLOSED, CallToolResult, PaginatedRequestParams

from app.config import get_settings
from app.errors import AppError, Forbidden, ToolError
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
# How long `close_all` spends on the whole pool, however many servers are in it.
CLOSE_ALL_TIMEOUT = 20
# Slack on top of a job's own timeout, covering the hand-off through the queue.
QUEUE_GRACE = 5
# In-flight calls per server. One `ClientSession` multiplexes requests by JSON-RPC id, so
# calls to one server run concurrently; the cap is what keeps a fan-out step from opening
# a hundred simultaneous requests against somebody's small MCP server.
MAX_CONCURRENT_CALLS = 8
# Guard against a server that paginates forever.
MAX_TOOL_PAGES = 20
# Stderr kept per stdio server, for the log line that explains a crash.
MAX_STDERR_CHARS = 4_000

_NO_CONTENT = "(the tool returned no content)"


class _ConnectionLost(Exception):
    """This connection is gone before the job could produce an answer.

    `started` is the difference between "the call never reached the server" — safe to run
    again on a fresh connection, which is what `_run_job` does — and "the call was in
    flight when the transport died", where the server may well have done the work
    (created the issue, sent the message) and a silent retry would do it twice.
    """

    def __init__(self, message: str, *, started: bool = False) -> None:
        super().__init__(message)
        self.started = started


# Everything a broken pipe, a dead subprocess or a dropped HTTP session can surface as.
# `MCPError(CONNECTION_CLOSED)` is the one the SDK raises for *every* pending and
# subsequent request once the transport dies — including the request that killed it — so
# it is the signal a connection is done for, not a per-call failure.
_TRANSPORT_EXCEPTIONS = (
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
    anyio.EndOfStream,
    ConnectionError,
    EOFError,
    BrokenPipeError,
)


def _is_transport_failure(exc: BaseException) -> bool:
    """Whether `exc` means the connection itself is unusable from now on."""
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        if isinstance(current, MCPError) and current.code == CONNECTION_CLOSED:
            return True
        if isinstance(current, _TRANSPORT_EXCEPTIONS):
            return True
        current = current.__cause__ or current.__context__
        seen += 1
    return False


class _StderrCapture:
    """A file-backed sink for a stdio server's stderr, logged (capped) when it closes.

    The SDK hands `errlog` straight to `anyio.open_process(stderr=...)`, so it has to be
    something with a real file descriptor — hence a temporary file rather than an
    in-memory buffer. The default is `sys.stderr`, which in a container means an MCP
    server's diagnostics land in the API's own log with nothing saying which server wrote
    them; this keeps the tail instead, so `mcp_server_stderr` can name it and a crash has
    an explanation attached.
    """

    def __init__(self, server: str) -> None:
        self.server = server
        self.file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")

    def tail(self) -> str:
        """The last `MAX_STDERR_CHARS` characters written, or "" if unreadable."""
        try:
            size = self.file.seek(0, os.SEEK_END)
            self.file.seek(max(0, size - MAX_STDERR_CHARS))
            return self.file.read()
        except (ValueError, OSError):  # already closed, or not seekable
            return ""

    def log(self, reason: str) -> None:
        text = self.tail().strip()
        if text:
            log.debug("mcp_server_stderr", server=self.server, reason=reason, stderr=text)

    def close(self, reason: str) -> None:
        self.log(reason)
        with contextlib.suppress(Exception):
            self.file.close()


@asynccontextmanager
async def _http_transport(url: str, headers: dict[str, str]) -> AsyncIterator[Any]:
    """Streamable HTTP streams, with our own httpx client so headers can be set.

    `Client(url)` would build its own client and there would be nowhere to put the bearer
    token; `streamable_http_client` only manages the lifetime of a client it created
    itself, so the one passed in is closed here.
    """
    http_client = create_mcp_http_client(headers=headers or None)
    async with http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            yield streams


def _str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _build_client(cfg: McpServerConfig) -> tuple[Client, _StderrCapture | None]:
    """An un-entered `Client` for `cfg` (plus its stderr sink, for stdio).

    Raises `ToolError` on a malformed config. Both transports are handed to `Client` as a
    ready-made transport rather than as a URL/`StdioServerParameters`, which is how the
    stdio `errlog` and the HTTP headers get in — `Client` builds its own otherwise.
    """
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
        params = StdioServerParameters(
            command=command, args=args, env=_str_map(config.get("env"))
        )
        errlog = _StderrCapture(cfg.name)
        return (
            Client(
                stdio_client(params, errlog=errlog.file),
                read_timeout_seconds=float(DEFAULT_CALL_TIMEOUT),
            ),
            errlog,
        )
    url = str(config.get("url") or "").strip()
    if not url:
        raise ToolError(
            f"MCP server '{cfg.name}' has no URL.", extra={"retryable": False}
        )
    return (
        Client(
            _http_transport(url, _str_map(config.get("headers"))),
            read_timeout_seconds=float(DEFAULT_CALL_TIMEOUT),
        ),
        None,
    )


STDIO_DISABLED_MESSAGE = (
    "stdio MCP servers are disabled: the command would run inside the API container, "
    "which has no login in front of it. Set MCP_ALLOW_STDIO=true to allow them, or "
    "register the server over http instead."
)


def stdio_allowed() -> bool:
    """Whether `stdio` MCP servers may be registered or connected on this deployment."""
    return get_settings().mcp_allow_stdio


def assert_stdio_allowed(transport: str) -> None:
    """Gate for the write paths (`app.services.mcp_servers`, `POST /mcp/servers/test`)."""
    if transport == "stdio" and not stdio_allowed():
        raise Forbidden(STDIO_DISABLED_MESSAGE)


async def _validate_config(cfg: McpServerConfig) -> None:
    """Pre-connect checks. Raises `ToolError` (permanent) when the config is refused."""
    if cfg.transport == "stdio":
        # Defense in depth: a row registered while stdio was allowed must stop working
        # if the deployment turns it off, not keep spawning processes.
        if not stdio_allowed():
            raise ToolError(STDIO_DISABLED_MESSAGE, extra={"retryable": False})
        return
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
                    title=tool.title or "",
                    output_schema=tool.output_schema
                    if isinstance(tool.output_schema, dict)
                    else None,
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


@dataclass
class _Job:
    """One call queued for a connection's worker."""

    fn: Callable[[Client], Awaitable[Any]]
    timeout: float
    future: asyncio.Future[Any]
    # Set the moment the worker starts the call, which is what tells a caller whose wait
    # ran out whether it was still queued or the server never answered.
    started: asyncio.Event = field(default_factory=asyncio.Event)


class _Connection:
    """A live client session plus the task that owns it.

    The worker task opens the client, then spawns one task per job (up to
    `MAX_CONCURRENT_CALLS`) rather than awaiting them in turn: a `ClientSession`
    multiplexes requests by JSON-RPC id, so two calls to the same server overlap instead
    of queueing behind each other — and a cancelled caller cancels its own call without
    touching anyone else's.
    """

    def __init__(self, cfg: McpServerConfig) -> None:
        self.cfg = cfg
        self.fingerprint = cfg.fingerprint
        self._jobs: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._alive = False
        self._fatal = False
        self._inflight: set[asyncio.Task[None]] = set()
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
        # Queued + running, so `call` can size its wait to the work ahead of it.
        self._pending = 0
        self._errlog: _StderrCapture | None = None

    @property
    def alive(self) -> bool:
        return (
            self._alive
            and not self._fatal
            and self._task is not None
            and not self._task.done()
        )

    # --- lifecycle -------------------------------------------------------------------

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
            client, self._errlog = _build_client(self.cfg)
            async with client:
                if not ready.done():
                    ready.set_result(None)
                try:
                    await self._loop(client)
                finally:
                    # Exiting the client's context tears the transport down under any
                    # call still in flight; cancel them first so each caller gets a
                    # `_ConnectionLost` instead of an error from inside the SDK.
                    await self._cancel_inflight()
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
            if self._errlog is not None:
                self._errlog.close("connection closed")

    async def _loop(self, client: Client) -> None:
        """Pull jobs until a sentinel or a fatal transport failure."""
        while not self._fatal:
            job = await self._jobs.get()
            if job is None or self._fatal:
                return
            if job.future.done():  # the caller gave up before we got here
                self._pending -= 1
                continue
            await self._slots.acquire()
            task = asyncio.create_task(
                self._run_one(client, job), name=f"mcp-{self.cfg.name}-call"
            )
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _run_one(self, client: Client, job: _Job) -> None:
        """Run one job, resolving its future. Never raises into the worker."""
        job.started.set()
        inner: asyncio.Task[Any] = asyncio.create_task(
            asyncio.wait_for(job.fn(client), job.timeout)
        )

        def _propagate_cancel(future: asyncio.Future[Any]) -> None:
            # `call` cancels the future when its caller is cancelled or gives up; the
            # request in flight has to go with it, or a cancelled run would leave the
            # server working (and the slot held) for the rest of the timeout.
            if future.cancelled():
                inner.cancel()

        job.future.add_done_callback(_propagate_cancel)
        try:
            value = await inner
        except asyncio.CancelledError:
            # Either the caller gave up (its future is already done) or the connection is
            # being torn down under us. The call did reach the server, so it is reported,
            # never silently repeated.
            if not job.future.done():
                job.future.set_exception(_ConnectionLost("call cancelled", started=True))
            raise
        except BaseException as exc:  # noqa: BLE001 — relayed to the caller
            if _is_transport_failure(exc):
                self._mark_fatal(exc)
                if not job.future.done():
                    job.future.set_exception(
                        _ConnectionLost(_error_text(exc), started=True)
                    )
            elif not job.future.done():
                job.future.set_exception(exc)
        else:
            if not job.future.done():
                job.future.set_result(value)
        finally:
            job.future.remove_done_callback(_propagate_cancel)
            self._pending -= 1
            self._slots.release()

    def _mark_fatal(self, exc: BaseException) -> None:
        """The transport is gone: stop serving and let `_serve` close the client.

        Without this the SDK would keep answering every later call with the same
        `Connection closed` error forever — the pool would hold a connection that can
        never work again, and (for stdio) never reap the subprocess.
        """
        if self._fatal:
            return
        self._fatal = True
        self._alive = False
        log.info("mcp_connection_lost", server=self.cfg.name, error=_error_text(exc))
        if self._errlog is not None:
            self._errlog.log("connection lost")
        # Wake the worker if it is blocked on the queue.
        self._jobs.put_nowait(None)

    async def _cancel_inflight(self) -> None:
        tasks = list(self._inflight)
        for task in tasks:
            task.cancel()
        if tasks:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), CLOSE_TIMEOUT
                )

    def _fail_pending(self) -> None:
        """Nobody is going to serve the queue any more — say so instead of hanging."""
        while True:
            try:
                job = self._jobs.get_nowait()
            except asyncio.QueueEmpty:
                return
            if job is None:
                continue
            if not job.future.done():
                job.future.set_exception(_ConnectionLost("connection closed"))

    # --- calling ---------------------------------------------------------------------

    def _wait_budget(self, timeout: float, ahead: int) -> float:
        """How long a caller waits: its own timeout plus the queue ahead of it.

        `MAX_CONCURRENT_CALLS` jobs run at a time, so a caller `ahead` jobs back may have
        to sit through that many *waves* of other people's timeouts before its own starts.
        Charging it only its own timeout would turn a busy server into a stream of
        spurious "did not answer" errors.
        """
        waves = max(0, ahead) // MAX_CONCURRENT_CALLS
        return timeout * (1 + waves) + QUEUE_GRACE

    async def call(self, fn: Callable[[Client], Awaitable[Any]], timeout: float) -> Any:
        """Run `fn` against the live session, from the worker task."""
        if not self.alive:
            raise _ConnectionLost("connection closed")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        job = _Job(fn=fn, timeout=timeout, future=future)
        ahead = self._pending
        self._pending += 1
        self._jobs.put_nowait(job)
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), self._wait_budget(timeout, ahead)
            )
        except asyncio.TimeoutError as exc:
            future.cancel()
            if not job.started.is_set():
                raise ToolError(
                    f"MCP server '{self.cfg.name}' is busy: the call was still queued "
                    f"behind {ahead} other call(s) when the wait ran out."
                ) from exc
            raise ToolError(
                f"MCP server '{self.cfg.name}' did not answer within {timeout:.0f}s."
            ) from exc
        except BaseException:
            # The caller was cancelled (a cancelled run, a step timeout): cancel the
            # future so the job is skipped if it is still queued, and so `_run_one`
            # cancels the request if it is already in flight.
            future.cancel()
            raise

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
        more than an error the user has to react to — but only for a job that never
        started (see `_ConnectionLost.started`).
        """
        for attempt in (0, 1):
            conn = await self._connection(cfg, reconnect=attempt == 1)
            try:
                return await conn.call(fn, timeout)
            except _ConnectionLost as exc:
                if exc.started:
                    # The request was already on the wire. Whether the server finished
                    # the work before it died is unknowable from here, so the failure
                    # goes back to the caller and the automation executor's retry policy
                    # — which the author can see and configure — decides, rather than
                    # this layer quietly running a side effect a second time.
                    raise ToolError(
                        f"The connection to MCP server '{cfg.name}' was lost while the "
                        f"call was in flight; it may or may not have run."
                    ) from exc
                if attempt:
                    raise ToolError(
                        f"Lost the connection to MCP server '{cfg.name}'."
                    ) from exc
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
        """Close every connection — called from the app's lifespan shutdown.

        All at once and under one budget: shutdown is not the moment to spend
        `CLOSE_TIMEOUT` per server in turn while the process is trying to exit.
        """
        names = list(self._connections)
        if not names:
            return
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                asyncio.gather(
                    *(self.disconnect(name) for name in names), return_exceptions=True
                ),
                CLOSE_ALL_TIMEOUT,
            )


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
        client, errlog = _build_client(cfg)
        try:
            async with client:
                return await _list_tools(client)
        finally:
            if errlog is not None:
                errlog.close("probe finished")

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
