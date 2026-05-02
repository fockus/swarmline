"""Tests for McpClient (tools/call + tools/list cache)."""

from __future__ import annotations

import pytest
from swarmline.runtime.thin.mcp_client import McpClient


class TestMcpClientCallTool:
    """Vyzov tools/call."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "server_url",
        [
            "file:///tmp/mcp.sock",
            "http://127.0.0.1/mcp",
            "http://169.254.169.254/latest/meta-data",
            "http://example.test/mcp",
        ],
    )
    async def test_call_tool_rejects_unsafe_url_without_http_request(
        self, monkeypatch: pytest.MonkeyPatch, server_url: str
    ) -> None:
        def fail_client(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("HTTP client must not be constructed for unsafe URL")

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fail_client
        )

        client = McpClient(timeout_seconds=1.0)
        result = await client.call_tool(server_url, "calc", {"x": 1})

        assert isinstance(result, dict)
        assert "error" in result
        assert "rejected" in result["error"].lower() or "blocked" in result[
            "error"
        ].lower()

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
    async def test_list_tools_rejects_unsafe_url_without_http_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_client(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("HTTP client must not be constructed for unsafe URL")

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fail_client
        )

        client = McpClient(timeout_seconds=1.0)
        tools = await client.list_tools("http://127.0.0.1/mcp")

        assert tools == []

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


class TestMcpClientResourcesSafety:
    @pytest.mark.asyncio
    async def test_list_resources_rejects_unsafe_url_without_http_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_client(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("HTTP client must not be constructed for unsafe URL")

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fail_client
        )

        client = McpClient(timeout_seconds=1.0)
        resources = await client.list_resources("http://169.254.169.254/mcp")

        assert resources == []

    @pytest.mark.asyncio
    async def test_read_resource_rejects_unsafe_url_without_http_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_client(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("HTTP client must not be constructed for unsafe URL")

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fail_client
        )

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("file:///tmp/mcp.sock", "file://doc")

        assert isinstance(result, dict)
        assert "error" in result
        assert "rejected" in result["error"].lower() or "blocked" in result[
            "error"
        ].lower()


class TestMcpClientPooling:
    @pytest.mark.asyncio
    async def test_reuses_one_async_client_until_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instances: list[object] = []

        class _Response:
            def __init__(self, data: dict) -> None:
                self._data = data

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self._data

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                _ = (args, kwargs)
                self.closed = False
                instances.append(self)

            async def post(self, *args, **kwargs):
                _ = (kwargs,)
                payload = args[1] if len(args) > 1 else kwargs.get("json", {})
                method = payload.get("method") if isinstance(payload, dict) else None
                if method == "tools/list":
                    return _Response({"result": {"tools": [{"name": "a"}]}})
                return _Response({"result": {"value": 42}})

            async def aclose(self) -> None:
                self.closed = True

        monkeypatch.setattr(
            "swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client
        )

        client = McpClient(timeout_seconds=1.0)
        await client.call_tool("https://example.test/mcp", "calc")
        await client.list_tools("https://example.test/mcp", force_refresh=True)
        await client.aclose()

        assert len(instances) == 1
        assert getattr(instances[0], "closed") is True
