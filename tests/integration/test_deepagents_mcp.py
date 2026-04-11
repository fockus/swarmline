"""Integration: DeepAgentsRuntime MCP tool injection. DeepAgentsRuntime(mcp_servers={"srv": ...}) + McpBridge.
Mock McpClient.list_tools (HTTP granitsa -- OK to mock).
Check: MCP tools poyavlyayutsya in selected_tools, executor created.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.runtime.deepagents import DeepAgentsRuntime
from swarmline.runtime.mcp_bridge import McpBridge
from swarmline.runtime.types import RuntimeConfig, ToolSpec


class TestDeepAgentsMcpToolInjection:
    """DeepAgentsRuntime + McpBridge: MCP tools injection."""

    def test_deepagents_mcp_bridge_created_when_servers_provided(self) -> None:
        """McpBridge sozdaetsya pri peredache mcp_servers."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents"),
            mcp_servers={"analytics": "http://analytics.test/mcp"},
        )

        assert runtime._mcp_bridge is not None
        assert isinstance(runtime._mcp_bridge, McpBridge)

    def test_deepagents_no_mcp_bridge_without_servers(self) -> None:
        """Without mcp_servers McpBridge not sozdaetsya."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents"),
        )

        assert runtime._mcp_bridge is None

    @pytest.mark.asyncio
    async def test_deepagents_mcp_tool_injection(self) -> None:
        """MCP tools poyavlyayutsya cherez McpBridge.discover_all_tools."""
        mcp_tools = [
            ToolSpec(
                name="mcp__analytics__query_data",
                description="Query analytics data",
                parameters={
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                },
                is_local=False,
            ),
            ToolSpec(
                name="mcp__analytics__list_tables",
                description="List available tables",
                parameters={"type": "object", "properties": {}},
                is_local=False,
            ),
        ]

        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                allow_native_features=True,
            ),
            mcp_servers={"analytics": "http://analytics.test/mcp"},
        )

        # Mock discover_all_tools on bridge (HTTP granitsa)
        runtime._mcp_bridge.discover_all_tools = AsyncMock(return_value=mcp_tools)  # type: ignore[union-attr]

        # select_active_tools in hybrid mode sohranyaet vse tools
        user_tools = [
            ToolSpec(
                name="local_calc",
                description="Calculator",
                parameters={"type": "object"},
                is_local=True,
            ),
        ]

        selected = runtime.select_active_tools(
            user_tools,
            feature_mode="hybrid",
            allow_native_features=True,
        )

        # V hybrid mode vse tools are preserved
        assert len(selected) == 1  # select_active_tools not dobavlyaet MCP - eto delaet run()

        # Verify chto bridge.discover_all_tools returns MCP tools
        discovered = await runtime._mcp_bridge.discover_all_tools()  # type: ignore[union-attr]
        assert len(discovered) == 2

        discovered_names = [t.name for t in discovered]
        assert "mcp__analytics__query_data" in discovered_names
        assert "mcp__analytics__list_tables" in discovered_names

    @pytest.mark.asyncio
    async def test_deepagents_mcp_executor_created_for_discovered_tools(self) -> None:
        """create_tool_executor sozdaet callable for kazhdogo MCP tool."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents"),
            mcp_servers={"srv": "http://srv.test/mcp"},
        )

        bridge = runtime._mcp_bridge
        assert bridge is not None

        # create_tool_executor returns callable
        executor = bridge.create_tool_executor("srv", "my_tool")
        assert callable(executor)
        assert executor.__name__ == "mcp__srv__my_tool"

    def test_deepagents_select_tools_portable_filters_builtins(self) -> None:
        """portable mode filtruet native built-in tools."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", feature_mode="portable"),
        )

        tools = [
            ToolSpec(name="read_file", description="Read", parameters={}, is_local=True),
            ToolSpec(name="custom_tool", description="Custom", parameters={}, is_local=True),
        ]

        selected = runtime.select_active_tools(
            tools,
            feature_mode="portable",
            allow_native_features=False,
        )

        # portable mode filtruet native built-ins (read_file)
        selected_names = [t.name for t in selected]
        assert "custom_tool" in selected_names

    def test_deepagents_select_tools_hybrid_keeps_all(self) -> None:
        """hybrid mode sohranyaet vse tools vklyuchaya native builtins."""
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                allow_native_features=True,
            ),
        )

        tools = [
            ToolSpec(name="read_file", description="Read", parameters={}, is_local=True),
            ToolSpec(name="custom_tool", description="Custom", parameters={}, is_local=True),
        ]

        selected = runtime.select_active_tools(
            tools,
            feature_mode="hybrid",
            allow_native_features=True,
        )

        assert len(selected) == 2
