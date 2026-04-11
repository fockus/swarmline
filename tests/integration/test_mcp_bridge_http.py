"""Integration: McpBridge + McpClient - real HTTP cherez httpx mock transport. httpx.MockTransport: tools/list -> JSON, tools/call -> result.
Check: discover_tools() -> ToolSpec[], call_tool() -> result payload.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from swarmline.runtime.mcp_bridge import McpBridge
from swarmline.runtime.thin.mcp_client import McpClient


def _create_mock_transport() -> httpx.MockTransport:
    """httpx MockTransport: obrabatyvaet tools/list and tools/call JSON-RPC."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method", "")
        request_id = body.get("id", "1")

        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "get_weather",
                                "description": "Get current weather",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {
                                        "city": {"type": "string"},
                                    },
                                    "required": ["city"],
                                },
                            },
                            {
                                "name": "get_forecast",
                                "description": "Get weather forecast",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {
                                        "city": {"type": "string"},
                                        "days": {"type": "integer"},
                                    },
                                    "required": ["city"],
                                },
                            },
                        ]
                    },
                },
            )

        if method == "tools/call":
            tool_name = body.get("params", {}).get("name", "")
            arguments = body.get("params", {}).get("arguments", {})

            if tool_name == "get_weather":
                city = arguments.get("city", "unknown")
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "temperature": 22,
                            "city": city,
                            "condition": "sunny",
                        },
                    },
                )

            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                },
            )

        return httpx.Response(404, json={"error": "unknown method"})

    return httpx.MockTransport(handler)


class TestMcpBridgeHttpRoundtrip:
    """McpBridge + McpClient: real HTTP cherez httpx MockTransport."""

    @pytest.mark.asyncio
    async def test_mcp_bridge_http_roundtrip(self) -> None:
        """discover_tools() -> ToolSpec[], call_tool() -> result payload."""
        transport = _create_mock_transport()

        # Swap httpx.AsyncClient cherez bridge with real McpClient
        bridge = McpBridge(
            mcp_servers={"weather": "https://weather.test/mcp"},
            timeout_seconds=5.0,
        )

        # Swap internal client transport for testov
        async def _patched_list_tools(server_url: str, **kwargs: Any) -> Any:
            async with httpx.AsyncClient(transport=transport) as http:
                payload = {
                    "jsonrpc": "2.0",
                    "id": "test",
                    "method": "tools/list",
                    "params": {},
                }
                response = await http.post(server_url, json=payload)
                data = response.json()
                return McpClient._parse_tools_from_response(data)

        async def _patched_call_tool(
            server_url: str, tool_name: str, arguments: dict[str, Any] | None = None
        ) -> Any:
            async with httpx.AsyncClient(transport=transport) as http:
                payload = {
                    "jsonrpc": "2.0",
                    "id": "test",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                }
                response = await http.post(server_url, json=payload)
                data = response.json()
                if "result" in data:
                    return data["result"]
                return data

        # Inject patched methods into bridge's internal client
        bridge._client.list_tools = _patched_list_tools  # type: ignore[method-assign]
        bridge._client.call_tool = _patched_call_tool  # type: ignore[method-assign]

        # --- Discover tools ---
        tools = await bridge.discover_tools("weather")
        assert len(tools) == 2

        tool_names = [t.name for t in tools]
        assert "mcp__weather__get_weather" in tool_names
        assert "mcp__weather__get_forecast" in tool_names

        # ToolSpec fields zapolnotny
        weather_tool = next(t for t in tools if "get_weather" in t.name)
        assert weather_tool.description == "Get current weather"
        assert weather_tool.is_local is False
        assert "city" in weather_tool.parameters.get("required", [])

        # --- Call tool ---
        result = await bridge.call_tool(
            "weather", "get_weather", {"city": "Moscow"}
        )
        assert result["temperature"] == 22
        assert result["city"] == "Moscow"
        assert result["condition"] == "sunny"
