"""Tests for ToolExecutor ThinRuntime."""

import json

import httpx
import pytest
from swarmline.agent.tool import tool
from swarmline.runtime.thin.executor import ToolExecutor


class TestToolExecutorLocal:
    """Execution local tools."""

    @pytest.mark.asyncio
    async def test_sync_local_tool(self) -> None:
        """Sync local tool runs via asyncio.to_thread."""

        def calc(args):
            return {"result": args["a"] + args["b"]}

        executor = ToolExecutor(local_tools={"calc": calc})
        result = await executor.execute("calc", {"a": 2, "b": 3})
        data = json.loads(result)
        assert data["result"] == 5

    @pytest.mark.asyncio
    async def test_async_local_tool(self) -> None:
        """Async local tool runs directly."""

        async def acalc(args):
            return {"result": args["x"] * 2}

        executor = ToolExecutor(local_tools={"acalc": acalc})
        result = await executor.execute("acalc", {"x": 10})
        data = json.loads(result)
        assert data["result"] == 20

    @pytest.mark.asyncio
    async def test_local_tool_error(self) -> None:
        """Error local tool -> JSON with error."""

        def bad_tool(args):
            raise ValueError("bad input")

        executor = ToolExecutor(local_tools={"bad": bad_tool})
        result = await executor.execute("bad", {})
        data = json.loads(result)
        assert "error" in data
        assert "bad input" in data["error"]

    @pytest.mark.asyncio
    async def test_local_tool_returns_string(self) -> None:
        """Local tool returns the string - not reversed."""

        def str_tool(args):
            return "hello world"

        executor = ToolExecutor(local_tools={"stool": str_tool})
        result = await executor.execute("stool", {})
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_decorated_tool_receives_keyword_arguments(self) -> None:
        """@tool handler(name=...) should receive kwargs, not the entire args dict."""

        @tool(name="greet", description="Greet user")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        executor = ToolExecutor(local_tools={"greet": greet.__tool_definition__.handler})
        result = await executor.execute("greet", {"name": "Alice"})

        assert result == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_decorated_tool_with_multiple_args_receives_kwargs(self) -> None:
        """Multiparameter @tool handler(a, b) should be called via kwargs."""

        @tool(name="add", description="Add two numbers")
        async def add(a: int, b: int) -> int:
            return a + b

        executor = ToolExecutor(local_tools={"add": add.__tool_definition__.handler})
        result = await executor.execute("add", {"a": 2, "b": 3})

        assert json.loads(result) == 5


class TestToolExecutorMcp:
    """MCP tools via HTTP JSON-RPC."""

    @pytest.mark.asyncio
    async def test_mcp_tool_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MCP tool is successfully called via configured server URL."""

        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"result": {"items": [1, 2, 3]}}

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

        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client)

        executor = ToolExecutor(mcp_servers={"iss": "https://example.test/mcp"})
        result = await executor.execute("mcp__iss__get_bonds", {"q": "test"})
        data = json.loads(result)
        assert data["items"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_mcp_tool_unknown_server(self) -> None:
        """MCP tool with not known server id returns error."""
        executor = ToolExecutor(mcp_servers={"funds": "https://example.test/mcp"})
        result = await executor.execute("mcp__iss__get_bonds", {"q": "test"})
        data = json.loads(result)
        assert "error" in data
        assert "не найден" in data["error"]

    @pytest.mark.asyncio
    async def test_mcp_tool_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MCP call timeout returns an understandable error."""

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
                raise httpx.TimeoutException("timeout")

        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", _Client)

        executor = ToolExecutor(
            mcp_servers={"iss": "https://example.test/mcp"}, timeout_seconds=0.01
        )
        result = await executor.execute("mcp__iss__get_bonds", {"q": "test"})
        data = json.loads(result)
        assert "error" in data
        assert "Таймаут" in data["error"]


class TestToolExecutorUnknown:
    """Not a known tool."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self) -> None:
        executor = ToolExecutor()
        result = await executor.execute("nonexistent", {})
        data = json.loads(result)
        assert "error" in data
        assert "не найден" in data["error"]


class TestToolExecutorProperties:
    """Properties and checks."""

    def test_has_tool_local(self) -> None:
        executor = ToolExecutor(local_tools={"calc": lambda x: x})
        assert executor.has_tool("calc") is True
        assert executor.has_tool("unknown") is False

    def test_has_tool_mcp(self) -> None:
        executor = ToolExecutor(mcp_servers={"iss": "https://example.test/mcp"})
        assert executor.has_tool("mcp__iss__bonds") is True
        assert executor.has_tool("mcp__funds__bonds") is False
        assert executor.has_tool("random") is False

    def test_local_tool_names(self) -> None:
        executor = ToolExecutor(local_tools={"a": lambda x: x, "b": lambda x: x})
        assert sorted(executor.local_tool_names) == ["a", "b"]
