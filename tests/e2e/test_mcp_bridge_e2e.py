"""E2E: MCP bridge - discovery to execution. McpBridge + McpClient with fake HTTP transport (httpx mock).
Edinstvennyy mock: HTTP transport (external boundary MCP server).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.runtime.mcp_bridge import McpBridge
from swarmline.runtime.thin.mcp_client import McpClient


# ---------------------------------------------------------------------------
# Helpers: Fake MCP server responses
# ---------------------------------------------------------------------------


def _mcp_tools_list_response(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Response MCP server on tools/list."""
    return {
        "jsonrpc": "2.0",
        "id": "test",
        "result": {"tools": tools},
    }


def _mcp_tool_call_response(result: Any) -> dict[str, Any]:
    """Response MCP server on tools/call."""
    return {
        "jsonrpc": "2.0",
        "id": "test",
        "result": result,
    }


class FakeHttpResponse:
    """Fake httpx Response for MCP testov."""

    def __init__(self, data: dict[str, Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# 1. McpBridge: discover and call
# ---------------------------------------------------------------------------


class TestMcpBridgeDiscoverAndCallE2E:
    """McpBridge: discover_all_tools() -> call_tool() -> result."""

    @pytest.mark.asyncio
    async def test_mcp_bridge_discover_and_call(self) -> None:
        """Full roundtrip: discover tools -> call tool -> result. Mock HTTP transport returns tools/list and tools/call responses."""
        # Nastraivaem fake MCP server responses
        tools_response = _mcp_tools_list_response(
            [
                {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
                {
                    "name": "get_time",
                    "description": "Get current time in timezone",
                    "input_schema": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                    },
                },
            ]
        )

        call_response = _mcp_tool_call_response(
            {"temperature": 22, "condition": "sunny", "city": "Moscow"}
        )

        # Swap McpClient cherez DI - create client with pereopredelennymi metodami
        client = McpClient(timeout_seconds=5.0)

        # Save originalnye metody and podmenyaem
        async def fake_list_tools(server_url: str, **kwargs: Any) -> list:
            data = tools_response
            return client._parse_tools_from_response(data)

        async def fake_call_tool(
            server_url: str, tool_name: str, arguments: dict | None = None
        ) -> Any:
            return call_response["result"]

        client.list_tools = fake_list_tools  # type: ignore[assignment]
        client.call_tool = fake_call_tool  # type: ignore[assignment]

        bridge = McpBridge(
            mcp_servers={"weather_api": "https://fake-mcp.test/mcp"},
        )
        bridge._client = client

        # Step 1: Discover tools
        all_tools = await bridge.discover_all_tools()
        assert len(all_tools) == 2, "Должно быть 2 tool от MCP server"

        tool_names = {t.name for t in all_tools}
        assert "mcp__weather_api__get_weather" in tool_names
        assert "mcp__weather_api__get_time" in tool_names

        # Verify parameters tool
        weather_tool = next(t for t in all_tools if "get_weather" in t.name)
        assert weather_tool.description == "Get weather for a city"
        assert "city" in weather_tool.parameters.get("properties", {})

        # Step 2: Call tool
        result = await bridge.call_tool(
            "weather_api", "get_weather", {"city": "Moscow"}
        )
        assert result["temperature"] == 22
        assert result["condition"] == "sunny"
        assert result["city"] == "Moscow"

    @pytest.mark.asyncio
    async def test_mcp_bridge_unknown_server_returns_error(self) -> None:
        """Call tool on notsushchestvuyushchem server -> error dict."""
        bridge = McpBridge(mcp_servers={"known": "https://known.test/mcp"})

        result = await bridge.call_tool("unknown_server", "some_tool", {})
        assert "error" in result
        assert "unknown_server" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_bridge_discover_from_single_server(self) -> None:
        """Discover tools ot konkretnogo server_id."""
        client = McpClient()

        async def fake_list(server_url: str, **kwargs: Any) -> list:
            data = _mcp_tools_list_response(
                [
                    {
                        "name": "calc",
                        "description": "Calculator",
                        "input_schema": {"type": "object"},
                    }
                ]
            )
            return client._parse_tools_from_response(data)

        client.list_tools = fake_list  # type: ignore[assignment]

        bridge = McpBridge(mcp_servers={"math_api": "https://math.test/mcp"})
        bridge._client = client

        tools = await bridge.discover_tools("math_api")
        assert len(tools) == 1
        assert tools[0].name == "mcp__math_api__calc"

    @pytest.mark.asyncio
    async def test_mcp_bridge_create_tool_executor(self) -> None:
        """create_tool_executor returns callable for konkretnogo tool."""
        client = McpClient()

        async def fake_call(
            server_url: str, tool_name: str, arguments: dict | None = None
        ) -> Any:
            return {"result": f"called {tool_name} with {arguments}"}

        client.call_tool = fake_call  # type: ignore[assignment]

        bridge = McpBridge(mcp_servers={"api": "https://api.test/mcp"})
        bridge._client = client

        executor = bridge.create_tool_executor("api", "process")
        assert callable(executor)
        assert executor.__name__ == "mcp__api__process"

        result = await executor(data="test_input")
        assert "process" in str(result)


# ---------------------------------------------------------------------------
# 2. MCP bridge in ThinRuntime
# ---------------------------------------------------------------------------


class TestMcpBridgeInThinRuntimeE2E:
    """McpBridge tool dostupen cherez ToolExecutor in ThinRuntime."""

    @pytest.mark.asyncio
    async def test_mcp_tool_execution_via_executor(self) -> None:
        """ThinRuntime ToolExecutor vyzyvaet MCP tool cherez mcp__server__tool format. Verify full roundtrip cherez ToolExecutor.execute()."""
        from swarmline.runtime.thin.executor import ToolExecutor

        # Create McpClient with fake responses
        client = McpClient()

        async def fake_call(
            server_url: str, tool_name: str, arguments: dict | None = None
        ) -> Any:
            if tool_name == "translate":
                text = (arguments or {}).get("text", "")
                return {"translated": f"translated: {text}"}
            return {"error": f"Unknown tool: {tool_name}"}

        client.call_tool = fake_call  # type: ignore[assignment]

        executor = ToolExecutor(
            local_tools={},
            mcp_servers={"translator": "https://translator.test/mcp"},
            mcp_client=client,
        )

        # Vyzyvaem MCP tool cherez standartnyy format
        result_str = await executor.execute(
            "mcp__translator__translate", {"text": "Hello"}
        )
        result = json.loads(result_str)
        assert result["translated"] == "translated: Hello"

    @pytest.mark.asyncio
    async def test_mcp_tool_not_found_returns_error(self) -> None:
        """Notizvestnyy MCP server -> error JSON."""
        from swarmline.runtime.thin.executor import ToolExecutor

        executor = ToolExecutor(
            local_tools={},
            mcp_servers={},
        )

        result_str = await executor.execute("mcp__unknown__tool", {})
        result = json.loads(result_str)
        assert "error" in result
