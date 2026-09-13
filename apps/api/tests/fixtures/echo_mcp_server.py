"""A minimal stdio MCP server used by the MCP client tests.

Launched as a subprocess by `tests/test_mcp_manager.py` and
`tests/integration/test_mcp_api.py` (`{"command": sys.executable, "args": [__file__]}`),
which is also the only MCP server guaranteed to work inside the API container: the image
has no node/npx, and `uvx <server>` needs PyPI access at first run.

Three tools, one per result shape the client has to map:
  - `echo`   → a text content block
  - `add`    → structured content (`{"sum": n}`)
  - `fail`   → an exception, which the server turns into `isError`
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool(description="Echo the given text back.")
def echo(text: str) -> str:
    return f"echo: {text}"


@server.tool(description="Add two integers and return the sum as structured output.")
def add(a: int, b: int) -> dict[str, int]:
    return {"sum": a + b}


@server.tool(description="Always fails, for testing error mapping.")
def fail() -> str:
    raise RuntimeError("boom")


if __name__ == "__main__":
    server.run("stdio")
