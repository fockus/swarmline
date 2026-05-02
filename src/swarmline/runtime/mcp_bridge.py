"""MCPBridge - library-level MCP tool discovery and execution.

Wraps MCPClient from Thin runtime, making MCP available to ANY runtime
(Thin, DeepAgents, Claude_SDK). Provides tool discovery, caching,
and executor factories for LangChain integration.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swarmline.runtime.thin.mcp_client import McpClient, resolve_mcp_server_url
from swarmline.runtime.types import ToolSpec


class McpBridge:
    """Library-level facade for MCP server interaction.

    Args:
      MCP_servers: Mapping server_id -> URL string or MCPServerSpec-like object.
      timeout_seconds: Timeout for MCP HTTP calls.
      tools_cache_ttl: TTL for tools/list cache per server.
    """

    def __init__(
        self,
        mcp_servers: dict[str, Any] | None = None,
        timeout_seconds: float = 30.0,
        tools_cache_ttl: float = 300.0,
    ) -> None:
        self._servers = mcp_servers or {}
        self._client = McpClient(
            timeout_seconds=timeout_seconds,
            tools_cache_ttl_seconds=tools_cache_ttl,
        )

    async def aclose(self) -> None:
        """Close the owned pooled MCP client."""
        await self._client.aclose()

    async def __aenter__(self) -> McpBridge:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        _ = exc
        await self.aclose()

    def _resolve_url(self, server_id: str) -> str | None:
        """Resolve server_id to URL string."""
        return resolve_mcp_server_url(self._servers, server_id)

    async def discover_tools(self, server_id: str) -> list[ToolSpec]:
        """Discover tools from a single MCP server.

        Returns ToolSpec list with names prefixed as MCP__{server_id}__{tool}.
        """
        url = self._resolve_url(server_id)
        if not url:
            return []

        raw_specs = await self._client.list_tools(url)
        return [
            ToolSpec(
                name=f"mcp__{server_id}__{spec.name}",
                description=spec.description,
                parameters=spec.parameters,
                is_local=False,
            )
            for spec in raw_specs
        ]

    async def discover_all_tools(self) -> list[ToolSpec]:
        """Discover tools from ALL configured MCP servers."""
        all_specs: list[ToolSpec] = []
        for server_id in self._servers:
            specs = await self.discover_tools(server_id)
            all_specs.extend(specs)
        return all_specs

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call a tool on a specific MCP server.

        Args:
          server_id: The server identifier.
          tool_name: Remote tool name (without MCP__ prefix).
          arguments: Tool arguments.

        Returns:
          Tool execution result or error dict.
        """
        url = self._resolve_url(server_id)
        if not url:
            return {"error": f"MCP server '{server_id}' not found"}
        return await self._client.call_tool(url, tool_name, arguments)

    def create_tool_executor(
        self, server_id: str, tool_name: str
    ) -> Callable[..., Any]:
        """Create an async callable executor for a specific MCP tool.

        Useful for LangChain StructuredTool integration.
        """

        async def _executor(**kwargs: Any) -> Any:
            return await self.call_tool(server_id, tool_name, kwargs)

        _executor.__name__ = f"mcp__{server_id}__{tool_name}"
        return _executor
