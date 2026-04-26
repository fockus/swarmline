"""Tests for McpClient (tools/call + tools/list cache)."""

from __future__ import annotations

import pytest
from swarmline.runtime.thin.mcp_client import McpClient


class TestMcpClientCallTool:
    """Vyzov tools/call."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"result": {"value": 42}}

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return None

            async def post(self, *args, **kwargs):
                _ = (args, kwargs)
                return _Response()

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client
        )

        client = McpClient(timeout_seconds=1.0)
        result = await client.call_tool(
            server_url="https://example.test/mcp",
            tool_name="calc",
            arguments={"x": 1},
        )
        assert isinstance(result, dict)
        assert result["value"] == 42

    @pytest.mark.asyncio
    async def test_call_tool_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return None

            async def post(self, *args, **kwargs):
                _ = (args, kwargs)
                raise RuntimeError("network down")

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client
        )

        client = McpClient(timeout_seconds=1.0)
        result = await client.call_tool(
            server_url="https://example.test/mcp",
            tool_name="calc",
            arguments={"x": 1},
        )
        assert isinstance(result, dict)
        assert "error" in result


class TestMcpClientListTools:
    """Discovery tools/list + keshirovanie."""

    @pytest.mark.asyncio
    async def test_list_tools_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "result": {
                        "tools": [
                            {
                                "name": "get_rates",
                                "description": "Получить ставки",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    }
                }

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return None

            async def post(self, *args, **kwargs):
                _ = (args, kwargs)
                return _Response()

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client
        )

        client = McpClient(timeout_seconds=1.0)
        tools = await client.list_tools("https://example.test/mcp")
        assert len(tools) == 1
        assert tools[0].name == "get_rates"
        assert tools[0].description == "Получить ставки"

    @pytest.mark.asyncio
    async def test_list_tools_uses_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"count": 0}

        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"result": {"tools": [{"name": "a", "description": "A"}]}}

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return None

            async def post(self, *args, **kwargs):
                _ = (args, kwargs)
                calls["count"] += 1
                return _Response()

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client
        )

        client = McpClient(timeout_seconds=1.0, tools_cache_ttl_seconds=100.0)
        first = await client.list_tools("https://example.test/mcp")
        second = await client.list_tools("https://example.test/mcp")
        assert len(first) == 1
        assert len(second) == 1
        assert calls["count"] == 1
