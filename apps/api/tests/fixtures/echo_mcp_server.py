"""A minimal stdio MCP server used by the MCP client tests.

Launched as a subprocess by `tests/test_mcp_manager.py` and
`tests/integration/test_mcp_api.py` (`{"command": sys.executable, "args": [__file__]}`),
which is also the only MCP server guaranteed to work inside the API container: the image
has no node/npx, and `uvx <server>` needs PyPI access at first run.

Runs over stdio by default; `--http <port>` serves the same tools over Streamable HTTP
at `/mcp`, which is how the HTTP transport gets covered without reaching the internet.

Five tools, one per behavior the client has to handle:
  - `echo`   → a text content block
  - `add`    → structured content (`{"sum": n}`)
  - `fail`   → an exception, which the server turns into `isError`
  - `crash`  → kills the process mid-request, so the client sees the transport die
  - `slow`   → sleeps, so a caller can cancel or time out mid-call (and `slow_marks`
               says afterwards whether the sleep ever finished)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool(title="Echo text", description="Echo the given text back.")
def echo(text: str) -> str:
    return f"echo: {text}"


@server.tool(description="Add two integers and return the sum as structured output.")
def add(a: int, b: int) -> dict[str, int]:
    return {"sum": a + b}


@server.tool(description="Always fails, for testing error mapping.")
def fail() -> str:
    raise RuntimeError("boom")


@server.tool(description="Kill the server process without answering.")
def crash() -> str:
    os._exit(1)


@server.tool(description="Sleep for `seconds`, then append a line to `marker`.")
async def slow(seconds: float, marker: str = "") -> str:
    await asyncio.sleep(seconds)
    if marker:
        Path(marker).write_text("finished")
    return "slept"


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run("stdio")
