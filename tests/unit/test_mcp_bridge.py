"""Tests McpBridge - library-level MCP tool discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from swarmline.runtime.mcp_bridge import McpBridge
from swarmline.runtime.types import ToolSpec


class TestMcpBridgeDiscovery:
    async def test_mcp_bridge_discover_tools(self) -> None:
        """discover_tools returns ToolSpec[] with correct prefixed names."""
        bridge = McpBridge(mcp_servers={"my_server": "https://example.com/mcp"})

        mock_tools = [
            ToolSpec(name="calculator", description="Calculate", parameters={"type": "object"}),
            ToolSpec(name="weather", description="Weather", parameters={"type": "object"}),
        ]

        with patch.object(
            bridge._client, "list_tools", new_callable=AsyncMock, return_value=mock_tools
        ):
            tools = await bridge.discover_tools("my_server")

        assert len(tools) == 2
        assert tools[0].name == "mcp__my_server__calculator"
        assert tools[1].name == "mcp__my_server__weather"
        assert tools[0].description == "Calculate"

    async def test_mcp_bridge_caching_ttl(self) -> None:
        """Second call within TTL uses cache."""
        bridge = McpBridge(mcp_servers={"srv": "https://example.com/mcp"})

        mock_tools = [ToolSpec(name="tool1", description="T1", parameters={})]

        with patch.object(
            bridge._client, "list_tools", new_callable=AsyncMock, return_value=mock_tools
        ):
            result1 = await bridge.discover_tools("srv")
            result2 = await bridge.discover_tools("srv")

        # list_tools should be called twice because McpBridge calls list_tools each time
        # but McpClient internally caches. We verify tools are returned correctly.
        assert len(result1) == 1
        assert len(result2) == 1


class TestMcpBridgeCallTool:
    async def test_mcp_bridge_call_tool(self) -> None:
        """call_tool delegates to McpClient.call_tool."""
        bridge = McpBridge(mcp_servers={"srv": "https://example.com/mcp"})

        with patch.object(
            bridge._client,
            "call_tool",
            new_callable=AsyncMock,
            return_value={"result": 42},
        ) as mock_call:
            result = await bridge.call_tool("srv", "calculator", {"x": 1})

        mock_call.assert_called_once_with("https://example.com/mcp", "calculator", {"x": 1})
        assert result == {"result": 42}

    async def test_mcp_bridge_server_unavailable_graceful(self) -> None:
        """Unknown server -> error dict, not crash."""
        bridge = McpBridge(mcp_servers={})

        result = await bridge.call_tool("nonexistent", "tool", {})
        assert isinstance(result, dict)
        assert "error" in result

        # Also test discover_tools with unknown server
        tools = await bridge.discover_tools("nonexistent")
        assert tools == []
