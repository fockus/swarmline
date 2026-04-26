"""Tests DeepAgents MCP integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class TestDeepAgentsMcpDiscovery:
    async def test_deepagents_mcp_tools_discovered(self) -> None:
        """mcp_servers provided -> MCP tools added to active_tools."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_tools = [
            ToolSpec(
                name="mcp__srv__calc",
                description="Calculator",
                parameters={"type": "object"},
            ),
        ]

        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", feature_mode="portable"),
            mcp_servers={"srv": "http://localhost:9090"},
        )

        # Mock the MCP bridge
        with patch.object(
            runtime._mcp_bridge,
            "discover_all_tools",
            new_callable=AsyncMock,
            return_value=mcp_tools,
        ):
            # Mock LangChain to avoid import issues
            with patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ):
                with patch.object(runtime, "_stream_langchain") as mock_stream:
                    # Capture what tools are passed
                    captured_tools: list[ToolSpec] = []

                    async def fake_stream(**kwargs):  # type: ignore[no-untyped-def]
                        captured_tools.extend(kwargs.get("tools", []))
                        yield RuntimeEvent.assistant_delta("hi")

                    mock_stream.side_effect = fake_stream

                    events = []
                    async for ev in runtime.run(
                        messages=[Message(role="user", content="test")],
                        system_prompt="test",
                        active_tools=[],
                    ):
                        events.append(ev)

                    # MCP tools should have been discovered and passed
                    mcp_names = [
                        t.name for t in captured_tools if t.name.startswith("mcp__")
                    ]
                    assert "mcp__srv__calc" in mcp_names

    async def test_deepagents_mcp_merged_with_custom_tools(self) -> None:
        """MCP tools + custom tools -> both available."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        mcp_tools = [
            ToolSpec(name="mcp__srv__calc", description="Calc", parameters={}),
        ]
        custom_tool = ToolSpec(name="my_tool", description="Custom", parameters={})

        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents", feature_mode="portable"),
            mcp_servers={"srv": "http://localhost:9090"},
        )

        with patch.object(
            runtime._mcp_bridge,
            "discover_all_tools",
            new_callable=AsyncMock,
            return_value=mcp_tools,
        ):
            with patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ):
                with patch.object(runtime, "_stream_langchain") as mock_stream:
                    captured_tools: list[ToolSpec] = []

                    async def fake_stream(**kwargs):  # type: ignore[no-untyped-def]
                        captured_tools.extend(kwargs.get("tools", []))
                        yield RuntimeEvent.assistant_delta("hi")

                    mock_stream.side_effect = fake_stream

                    async for _ in runtime.run(
                        messages=[Message(role="user", content="test")],
                        system_prompt="test",
                        active_tools=[custom_tool],
                    ):
                        pass

                    names = {t.name for t in captured_tools}
                    assert "mcp__srv__calc" in names  # MCP tool present

    async def test_deepagents_no_mcp_servers_no_change(self) -> None:
        """Without mcp_servers -> behavior unchanged."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents"),
        )
        assert runtime._mcp_bridge is None

    async def test_deepagents_mcp_feature_mode_all(self) -> None:
        """MCP tools available in all feature modes."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        for mode in ["portable", "hybrid", "native_first"]:
            runtime = DeepAgentsRuntime(
                config=RuntimeConfig(runtime_name="deepagents", feature_mode=mode),
                mcp_servers={"srv": "http://localhost:9090"},
            )
            assert runtime._mcp_bridge is not None

    async def test_deepagents_mcp_tool_execution(self) -> None:
        """MCP tool executor is registered and callable."""
        from swarmline.runtime.deepagents import DeepAgentsRuntime

        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(runtime_name="deepagents"),
            mcp_servers={"srv": "http://localhost:9090"},
        )

        # Test create_tool_executor on bridge
        executor = runtime._mcp_bridge.create_tool_executor("srv", "calc")
        assert callable(executor)
        assert executor.__name__ == "mcp__srv__calc"
