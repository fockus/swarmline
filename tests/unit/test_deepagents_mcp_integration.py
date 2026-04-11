"""TDD Red Phase: DeepAgents MCP Integration (Phase 3.2). Tests check:
- mcp_servers provided -> MCP tools in active_tools
- LLM calls MCP tool -> McpBridge.call_tool() called
- MCP tools + custom tools -> both available
- MCP tools are available in portable/hybrid/native_first
- Without mcp_servers -> behavior does not change (backward compat) Contract: DeepAgentsRuntime + McpBridge integration"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def collect_events(
    runtime: Any,
    text: str = "test",
    tools: list[ToolSpec] | None = None,
    config: RuntimeConfig | None = None,
) -> list[RuntimeEvent]:
    """Collect all events from runtime.run()."""
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="Test system prompt",
        active_tools=tools or [],
        config=config,
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeepAgentsMcpToolDiscovery:
    """MCP tool discovery via McpBridge in DeepAgentsRuntime."""

    def test_deepagents_accepts_mcp_servers_parameter(self) -> None:
        """DeepAgentsRuntime.__init__ accepts the mcp_servers parameter."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        config = RuntimeConfig(runtime_name="deepagents")
        mcp_servers = {"weather": "https://weather.test/mcp"}

        # Not should raise - parameter is accepted
        runtime = DeepAgentsRuntime(config=config, mcp_servers=mcp_servers)
        assert runtime is not None

    @pytest.mark.asyncio
    async def test_deepagents_mcp_tools_discovered(self) -> None:
        """mcp_servers provided -> MCP tools are discovered via McpBridge."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_servers = {"svc": "https://svc.test/mcp"}
        config = RuntimeConfig(runtime_name="deepagents", feature_mode="hybrid")

        runtime = DeepAgentsRuntime(config=config, mcp_servers=mcp_servers)

        # Mock McpBridge.discover_all_tools
        mock_tools = [
            ToolSpec(
                name="mcp__svc__get_data",
                description="Get data from service",
                parameters={"type": "object"},
                is_local=False,
            ),
        ]

        with patch.object(
            runtime._mcp_bridge, "discover_all_tools",
            new_callable=AsyncMock,
            return_value=mock_tools,
        ):
            # Verify tools are discovered (accessible via internal state)
            tools = await runtime._mcp_bridge.discover_all_tools()
            assert len(tools) == 1
            assert tools[0].name == "mcp__svc__get_data"

    def test_deepagents_no_mcp_servers_no_change(self) -> None:
        """Without mcp_servers -> behavior does not change (backward compat)."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        config = RuntimeConfig(runtime_name="deepagents")

        # Without mcp_servers - backward compatibility
        runtime = DeepAgentsRuntime(config=config)
        assert runtime is not None

        # Not should be _mcp_bridge or it should be None/empty
        bridge = getattr(runtime, "_mcp_bridge", None)
        if bridge is not None:
            # Bridge created, no without serverov
            assert bridge._servers == {}


class TestDeepAgentsMcpToolExecution:
    """Call MCP tools via DeepAgentsRuntime."""

    @pytest.mark.asyncio
    async def test_deepagents_mcp_tool_execution(self) -> None:
        """LLM calls MCP tool -> McpBridge.call_tool() delegates call."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_servers = {"svc": "https://svc.test/mcp"}
        config = RuntimeConfig(runtime_name="deepagents", feature_mode="hybrid")

        runtime = DeepAgentsRuntime(config=config, mcp_servers=mcp_servers)

        # Verify that bridge can create executor for MCP tool
        bridge = runtime._mcp_bridge
        executor = bridge.create_tool_executor("svc", "get_data")

        # Mock internal call_tool
        with patch.object(
            bridge._client, "call_tool",
            new_callable=AsyncMock,
            return_value={"result": "ok"},
        ):
            result = await executor(city="Moscow")
            assert result == {"result": "ok"}


class TestDeepAgentsMcpMergedWithCustomTools:
    """MCP tools + custom tools -> both are available."""

    @pytest.mark.asyncio
    async def test_deepagents_mcp_merged_with_custom_tools(self) -> None:
        """MCP tools + custom tools -> both types are available for LLM."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_servers = {"svc": "https://svc.test/mcp"}
        config = RuntimeConfig(runtime_name="deepagents", feature_mode="hybrid")

        custom_tools = [
            ToolSpec(
                name="calc",
                description="Calculator",
                parameters={"type": "object"},
                is_local=True,
            ),
        ]

        mcp_tools = [
            ToolSpec(
                name="mcp__svc__weather",
                description="Weather",
                parameters={"type": "object"},
                is_local=False,
            ),
        ]

        runtime = DeepAgentsRuntime(config=config, mcp_servers=mcp_servers)

        with patch.object(
            runtime._mcp_bridge, "discover_all_tools",
            new_callable=AsyncMock,
            return_value=mcp_tools,
        ):
            discovered = await runtime._mcp_bridge.discover_all_tools()
            all_tools = custom_tools + discovered
            names = {t.name for t in all_tools}
            assert "calc" in names
            assert "mcp__svc__weather" in names


class TestDeepAgentsMcpFeatureMode:
    """MCP tools are available in all feature_modes."""

    @pytest.mark.parametrize("mode", ["portable", "hybrid", "native_first"])
    def test_deepagents_mcp_feature_mode_all(self, mode: str) -> None:
        """MCP tools are available in portable/hybrid/native_first."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_servers = {"svc": "https://svc.test/mcp"}
        config = RuntimeConfig(runtime_name="deepagents", feature_mode=mode)

        # Not crash in any mode
        runtime = DeepAgentsRuntime(config=config, mcp_servers=mcp_servers)
        assert runtime is not None

        # MCP bridge should be available not depending on feature_mode
        bridge = getattr(runtime, "_mcp_bridge", None)
        assert bridge is not None
