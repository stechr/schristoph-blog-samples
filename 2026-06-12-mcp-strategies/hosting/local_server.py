"""local_server.py — The "start here" MCP server: stdio transport.

The AWS guidance is candid that most MCP usage today is local: the server runs
as a subprocess on the user's machine and talks JSON-RPC over stdio. There is
no client-to-server authentication to configure — the server runs with the
user's own local credentials and files. That makes it the right place to start
and to iterate.

This uses the official `mcp` SDK (FastMCP). Point any MCP client at it, e.g. an
MCP-aware IDE/CLI config:

    {
      "mcpServers": {
        "demo-local": { "command": "uv",
          "args": ["run", "--with", "mcp", "python", "local_server.py"] }
      }
    }

Run directly:
    uv run --with mcp python local_server.py
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-strategies-demo-local")


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back. The simplest possible tool — useful to confirm the
    server is wired up and reachable from your client."""
    return message


@mcp.tool()
def word_count(text: str) -> dict:
    """Count words and characters in a block of text. Returns both counts.
    A read-only tool: it computes, it does not mutate anything."""
    words = len(text.split())
    return {"words": words, "characters": len(text)}


if __name__ == "__main__":
    # stdio transport: no network, no auth — the local starting point.
    mcp.run(transport="stdio")
