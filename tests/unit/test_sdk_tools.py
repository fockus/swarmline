"""Тесты для sdk_tools — in-process MCP tools wrapper."""

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
from cognitia.runtime.sdk_tools import create_mcp_server, mcp_tool


class TestMcpTool:
    """@mcp_tool декоратор — обёртка над SDK @tool."""

    def test_decorator_returns_sdk_mcp_tool(self) -> None:
        """@mcp_tool возвращает SdkMcpTool."""

        @mcp_tool("greet", "Greet user", {"name": str})
        async def greet(args):
            return {"content": [{"type": "text", "text": f"Hi {args['name']}"}]}

        assert greet.name == "greet"
        assert greet.description == "Greet user"

    def test_decorator_preserves_handler(self) -> None:
        """Handler сохраняется в SdkMcpTool."""

        @mcp_tool("add", "Add two numbers", {"a": float, "b": float})
        async def add(args):
            return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}

        assert add.handler is not None

    @pytest.mark.asyncio
    async def test_handler_callable(self) -> None:
        """Handler вызывается корректно."""

        @mcp_tool("echo", "Echo input", {"text": str})
        async def echo(args):
            return {"content": [{"type": "text", "text": args["text"]}]}

        result = await echo.handler({"text": "hello"})
        assert result["content"][0]["text"] == "hello"


class TestCreateMcpServer:
    """create_mcp_server — обёртка над SDK create_sdk_mcp_server."""

    def test_creates_sdk_config(self) -> None:
        """create_mcp_server возвращает McpSdkServerConfig."""

        @mcp_tool("test_tool", "Test", {"x": str})
        async def test_tool(args):
            return {"content": [{"type": "text", "text": "ok"}]}

        config = create_mcp_server("test_server", tools=[test_tool])

        assert config["type"] == "sdk"
        assert config["name"] == "test_server"
        assert "instance" in config

    def test_empty_tools_creates_server(self) -> None:
        """Сервер без инструментов — валидный."""
        config = create_mcp_server("empty_server")
        assert config["type"] == "sdk"

    def test_custom_version(self) -> None:
        """Кастомная версия сервера."""
        config = create_mcp_server("versioned", version="2.0.0")
        assert config["type"] == "sdk"

    def test_multiple_tools(self) -> None:
        """Сервер с несколькими инструментами."""

        @mcp_tool("tool_a", "Tool A", {"x": str})
        async def tool_a(args):
            return {"content": [{"type": "text", "text": "a"}]}

        @mcp_tool("tool_b", "Tool B", {"y": int})
        async def tool_b(args):
            return {"content": [{"type": "text", "text": "b"}]}

        config = create_mcp_server("multi", tools=[tool_a, tool_b])
        assert config["type"] == "sdk"
