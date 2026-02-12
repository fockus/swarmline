"""Тесты для ClaudeOptionsBuilder и _spec_to_sdk_config — фабрика опций SDK."""


from cognitia.runtime.options_builder import (
    ClaudeOptionsBuilder,
    _build_sse_config,
    _build_stdio_config,
    _build_url_config,
    _spec_to_sdk_config,
)
from cognitia.skills.types import McpServerSpec


class TestSpecToSdkConfig:
    """Конвертация McpServerSpec в SDK-совместимый dict."""

    def test_url_transport(self) -> None:
        """URL transport → SSE dict (url/http endpoints → type=sse для SDK)."""
        spec = McpServerSpec(name="iss", transport="url", url="https://example.com/mcp")
        result = _spec_to_sdk_config(spec)
        assert result == {"type": "sse", "url": "https://example.com/mcp"}

    def test_http_transport(self) -> None:
        """HTTP transport → аналогично url (SSE)."""
        spec = McpServerSpec(name="iss", transport="http", url="https://example.com/mcp")
        result = _spec_to_sdk_config(spec)
        assert result == {"type": "sse", "url": "https://example.com/mcp"}

    def test_sse_transport(self) -> None:
        """SSE transport → type: sse + url."""
        spec = McpServerSpec(name="iss", transport="sse", url="https://example.com/sse")
        result = _spec_to_sdk_config(spec)
        assert result == {"type": "sse", "url": "https://example.com/sse"}

    def test_stdio_transport_minimal(self) -> None:
        """STDIO transport → type: stdio + command."""
        spec = McpServerSpec(name="local", transport="stdio", command="/usr/bin/tool")
        result = _spec_to_sdk_config(spec)
        assert result["type"] == "stdio"
        assert result["command"] == "/usr/bin/tool"
        assert "args" not in result

    def test_stdio_transport_with_args_and_env(self) -> None:
        """STDIO transport с args и env."""
        spec = McpServerSpec(
            name="local", transport="stdio", command="node",
            args=["server.js", "--port=3000"],
            env={"NODE_ENV": "production"},
        )
        result = _spec_to_sdk_config(spec)
        assert result["command"] == "node"
        assert result["args"] == ["server.js", "--port=3000"]
        assert result["env"] == {"NODE_ENV": "production"}

    def test_unknown_transport_defaults_to_url(self) -> None:
        """Неизвестный transport → fallback на url-конфиг."""
        spec = McpServerSpec(name="x", transport="url", url="http://fallback")
        result = _spec_to_sdk_config(spec)
        assert "url" in result

    def test_missing_url_returns_empty_string(self) -> None:
        """Без url → пустая строка."""
        spec = McpServerSpec(name="x", transport="url")
        result = _spec_to_sdk_config(spec)
        assert result["url"] == ""


class TestBuildUrlConfig:
    """Отдельные builder-функции."""

    def test_build_url(self) -> None:
        spec = McpServerSpec(name="t", url="http://test")
        assert _build_url_config(spec) == {"type": "sse", "url": "http://test"}

    def test_build_sse(self) -> None:
        spec = McpServerSpec(name="t", url="http://test")
        assert _build_sse_config(spec) == {"type": "sse", "url": "http://test"}

    def test_build_stdio(self) -> None:
        spec = McpServerSpec(name="t", command="cmd")
        result = _build_stdio_config(spec)
        assert result["type"] == "stdio"
        assert result["command"] == "cmd"


class TestClaudeOptionsBuilder:
    """ClaudeOptionsBuilder — сборка ClaudeAgentOptions."""

    def test_build_basic(self) -> None:
        """Базовая сборка с default model policy."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="Ты — Freedom",
        )
        assert opts.model == "sonnet"
        assert opts.system_prompt == "Ты — Freedom"

    def test_build_with_mcp_servers(self) -> None:
        """Сборка с MCP-серверами."""
        builder = ClaudeOptionsBuilder()
        servers = {
            "iss": McpServerSpec(name="iss", url="http://iss.test"),
            "fin": McpServerSpec(name="fin", url="http://fin.test"),
        }
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            mcp_servers=servers,
        )
        assert "iss" in opts.mcp_servers
        assert "fin" in opts.mcp_servers

    def test_build_with_custom_model_policy(self) -> None:
        """Пользовательская model policy."""
        from cognitia.runtime.model_policy import ModelPolicy

        policy = ModelPolicy(
            default_model="custom-sonnet",
            escalation_model="custom-opus",
            escalate_roles={"strategy_planner"},
        )
        builder = ClaudeOptionsBuilder(model_policy=policy)
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.model == "custom-sonnet"

        opts_escalated = builder.build(
            role_id="strategy_planner", system_prompt="test"
        )
        assert opts_escalated.model == "custom-opus"

    def test_build_with_tool_failure_escalation(self) -> None:
        """Эскалация модели из-за ошибок tools."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach", system_prompt="test",
            tool_failure_count=10,
        )
        assert opts.model == "opus"

    def test_build_permission_mode(self) -> None:
        """permission_mode = bypassPermissions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.permission_mode == "bypassPermissions"

    def test_build_with_cwd(self) -> None:
        """cwd передаётся в опции."""
        builder = ClaudeOptionsBuilder(cwd="/tmp/test")
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.cwd == "/tmp/test"
