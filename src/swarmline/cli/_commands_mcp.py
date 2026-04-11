"""MCP serve CLI command -- delegates to the MCP server entry point."""

from __future__ import annotations

import click


@click.command(name="mcp-serve")
@click.option(
    "--mode",
    default="auto",
    type=click.Choice(["auto", "headless", "full"]),
    help="Server mode",
)
def mcp_serve(mode: str) -> None:
    """Start the Swarmline MCP server (stdio transport)."""
    from swarmline.mcp._server import create_server

    server = create_server(mode=mode)
    server.run(transport="stdio")
