"""Tests for ClaudeOptionsBuilder and _spec_to_sdk_config - fabrika optsiy SDK."""

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

pytestmark = pytest.mark.requires_claude_sdk

from swarmline.runtime.options_builder import (  # noqa: E402
    ClaudeOptionsBuilder,
    _build_sse_config,
    _build_stdio_config,
    _build_url_config,
    _spec_to_sdk_config,
)
from swarmline.skills.types import McpServerSpec  # noqa: E402


class TestSpecToSdkConfig:
    """Conversion McpServerSpec in SDK-compatible dict."""

    def test_url_transport(self) -> None:
        """URL transport -> Streamable HTTP (type=http for SDK)."""
        spec = McpServerSpec(name="iss", transport="url", url="https://example.com/mcp")
        result = _spec_to_sdk_config(spec)
        assert result == {"type": "http", "url": "https://example.com/mcp"}

    def test_http_transport(self) -> None:
        """HTTP transport -> analogichno url (Streamable HTTP)."""
        spec = McpServerSpec(
            name="iss", transport="http", url="https://example.com/mcp"
        )
        result = _spec_to_sdk_config(spec)
        assert result == {"type": "http", "url": "https://example.com/mcp"}

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
        """STDIO transport with args and env."""
        spec = McpServerSpec(
            name="local",
            transport="stdio",
            command="node",
            args=["server.js", "--port=3000"],
            env={"NODE_ENV": "production"},
        )
        result = _spec_to_sdk_config(spec)
        assert result["command"] == "node"
        assert result["args"] == ["server.js", "--port=3000"]
        assert result["env"] == {"NODE_ENV": "production"}

    def test_unknown_transport_defaults_to_url(self) -> None:
        """Notizvestnyy transport -> fallback on url-config."""
        spec = McpServerSpec(
            name="x",
            transport="url",
            url="http://127.0.0.1:8080/mcp",
            allow_private_network=True,
            allow_insecure_http=True,
        )
        result = _spec_to_sdk_config(spec)
        assert "url" in result

    def test_missing_url_rejected_fail_fast(self) -> None:
        """Without url builder must fail fast."""
        spec = McpServerSpec(name="x", transport="url")
        with pytest.raises(ValueError, match="Unsafe MCP server URL"):
            _spec_to_sdk_config(spec)


class TestBuildUrlConfig:
    """Otdelnye builder-funktsii."""

    def test_build_url(self) -> None:
        spec = McpServerSpec(name="t", url="https://test.example")
        assert _build_url_config(spec) == {
            "type": "http",
            "url": "https://test.example",
        }

    def test_build_sse(self) -> None:
        spec = McpServerSpec(name="t", url="https://test.example")
        assert _build_sse_config(spec) == {"type": "sse", "url": "https://test.example"}

    def test_build_stdio(self) -> None:
        spec = McpServerSpec(name="t", command="cmd")
        result = _build_stdio_config(spec)
        assert result["type"] == "stdio"
        assert result["command"] == "cmd"


class TestClaudeOptionsBuilder:
    """ClaudeOptionsBuilder - assembly ClaudeAgentOptions."""

    def test_build_basic(self) -> None:
        """Basic assembly with default model policy."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="Ты — Freedom",
        )
        assert opts.model == "sonnet"
        assert opts.system_prompt == "Ты — Freedom"

    def test_build_with_mcp_servers(self) -> None:
        """Sborka with MCP-serverami."""
        builder = ClaudeOptionsBuilder()
        servers = {
            "iss": McpServerSpec(
                name="iss",
                url="http://127.0.0.1:9001/mcp",
                allow_private_network=True,
                allow_insecure_http=True,
            ),
            "fin": McpServerSpec(name="fin", url="https://fin.test"),
        }
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            mcp_servers=servers,
        )
        assert "iss" in opts.mcp_servers
        assert "fin" in opts.mcp_servers

    def test_rejects_private_network_mcp_url_by_default(self) -> None:
        spec = McpServerSpec(name="iss", url="http://127.0.0.1:9001/mcp")
        with pytest.raises(ValueError, match="Unsafe MCP server URL"):
            _spec_to_sdk_config(spec)

    def test_build_with_custom_model_policy(self) -> None:
        """Userskaya model policy."""
        from swarmline.runtime.model_policy import ModelPolicy

        policy = ModelPolicy(
            default_model="custom-sonnet",
            escalation_model="custom-opus",
            escalate_roles={"strategy_planner"},
        )
        builder = ClaudeOptionsBuilder(model_policy=policy)
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.model == "custom-sonnet"

        opts_escalated = builder.build(role_id="strategy_planner", system_prompt="test")
        assert opts_escalated.model == "custom-opus"

    def test_build_with_tool_failure_escalation(self) -> None:
        """Eskalatsiya models from-za oshibok tools."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            tool_failure_count=10,
        )
        assert opts.model == "opus"

    def test_build_permission_mode_default(self) -> None:
        """Po umolchaniyu permission_mode = bypassPermissions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.permission_mode == "bypassPermissions"

    def test_build_permission_mode_override(self) -> None:
        """Mozhno yavno zadat permission_mode."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            permission_mode="plan",
        )
        assert opts.permission_mode == "plan"

    def test_build_with_cwd(self) -> None:
        """cwd peredaetsya in optsii."""
        builder = ClaudeOptionsBuilder(cwd="/tmp/test")
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.cwd == "/tmp/test"

    def test_default_setting_sources_empty(self) -> None:
        """Po umolchaniyu setting_sources=[] - not chitaem CLAUDE.md and .claude/settings.json. CLAUDE.md contains developer-facing instruktsii (arhitektura, commands), kotorye konfliktuyut with rolyu finansovogo koucha from system_prompt."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.setting_sources == []

    def test_explicit_setting_sources_override(self) -> None:
        """YAvno peredannye setting_sources imeyut prioritet."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            setting_sources=["project", "user"],
        )
        assert opts.setting_sources == ["project", "user"]

    def test_override_model_has_priority(self) -> None:
        """override_model imeet prioritet nad ModelPolicy."""
        builder = ClaudeOptionsBuilder(override_model="custom-model-v2")
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.model == "custom-model-v2"

    def test_build_with_thinking_config(self) -> None:
        """thinking config peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            thinking={"type": "enabled", "budget_tokens": 16000},
        )
        assert opts.thinking is not None
        assert opts.thinking["type"] == "enabled"
        assert opts.thinking["budget_tokens"] == 16000

    def test_build_with_thinking_adaptive(self) -> None:
        """thinking adaptive config works."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            thinking={"type": "adaptive"},
        )
        assert opts.thinking is not None
        assert opts.thinking["type"] == "adaptive"

    def test_build_with_deprecated_max_thinking_tokens(self) -> None:
        """Deprecated max_thinking_tokens converts to thinking config."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            max_thinking_tokens=16000,
        )
        assert opts.thinking is not None
        assert opts.thinking["type"] == "enabled"
        assert opts.thinking["budget_tokens"] == 16000

    def test_thinking_takes_priority_over_max_thinking_tokens(self) -> None:
        """thinking dict takes priority over deprecated max_thinking_tokens."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            thinking={"type": "adaptive"},
            max_thinking_tokens=16000,
        )
        assert opts.thinking["type"] == "adaptive"

    def test_thinking_invalid_type_raises(self) -> None:
        """Invalid thinking type raises ValueError (fail-fast)."""
        builder = ClaudeOptionsBuilder()
        with pytest.raises(ValueError, match="Unknown thinking type"):
            builder.build(
                role_id="coach",
                system_prompt="test",
                thinking={"type": "turbo"},
            )

    def test_build_with_sandbox(self) -> None:
        """sandbox nastroyki are passed in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        sandbox = {"enabled": True, "autoAllowBashIfSandboxed": True}
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            sandbox=sandbox,
        )
        assert opts.sandbox == sandbox

    def test_build_with_env(self) -> None:
        """env peremennye are passed in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            env={"MY_VAR": "value"},
        )
        assert opts.env == {"MY_VAR": "value"}

    def test_build_default_env_empty(self) -> None:
        """Po umolchaniyu env - empty dict."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.env == {}

    def test_build_with_agents(self) -> None:
        """agents opredeleniya are passed in ClaudeAgentOptions."""
        from claude_agent_sdk import AgentDefinition

        builder = ClaudeOptionsBuilder()
        agents = {
            "researcher": AgentDefinition(
                description="Research agent",
                prompt="You are a researcher",
            ),
        }
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            agents=agents,
        )
        assert opts.agents is not None
        assert "researcher" in opts.agents

    def test_build_with_output_format(self) -> None:
        """output_format (structured output) peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        schema = {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        }
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            output_format=schema,
        )
        assert opts.output_format == schema

    def test_build_default_output_format_none(self) -> None:
        """Po umolchaniyu output_format = None."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.output_format is None

    def test_build_with_continue_conversation(self) -> None:
        """continue_conversation peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            continue_conversation=True,
        )
        assert opts.continue_conversation is True

    def test_build_default_continue_conversation_false(self) -> None:
        """Po umolchaniyu continue_conversation = False."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.continue_conversation is False

    def test_build_with_resume(self) -> None:
        """resume (session_id) peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            resume="session-abc-123",
        )
        assert opts.resume == "session-abc-123"

    def test_build_with_fork_session(self) -> None:
        """fork_session peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            fork_session=True,
        )
        assert opts.fork_session is True

    def test_build_with_betas(self) -> None:
        """betas (1M context) peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            betas=["context-1m-2025-08-07"],
        )
        assert opts.betas == ["context-1m-2025-08-07"]

    def test_build_default_betas_empty(self) -> None:
        """Po umolchaniyu betas = []."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(role_id="coach", system_prompt="test")
        assert opts.betas == []

    def test_build_with_plugins(self) -> None:
        """plugins are passed in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        plugins = [{"type": "local", "path": "/path/to/plugin"}]
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            plugins=plugins,
        )
        assert opts.plugins == plugins

    def test_build_with_include_partial_messages(self) -> None:
        """include_partial_messages peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            include_partial_messages=True,
        )
        assert opts.include_partial_messages is True

    def test_build_with_enable_file_checkpointing(self) -> None:
        """enable_file_checkpointing peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            enable_file_checkpointing=True,
        )
        assert opts.enable_file_checkpointing is True

    def test_build_with_max_budget_usd(self) -> None:
        """max_budget_usd peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            max_budget_usd=5.0,
        )
        assert opts.max_budget_usd == 5.0

    def test_build_with_fallback_model(self) -> None:
        """fallback_model peredaetsya in ClaudeAgentOptions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            fallback_model="haiku",
        )
        assert opts.fallback_model == "haiku"

    def test_build_with_hooks(self) -> None:
        """hooks are passed in ClaudeAgentOptions."""
        from claude_agent_sdk import HookMatcher

        builder = ClaudeOptionsBuilder()

        async def my_hook(input_data, tool_use_id, context):
            return {"continue_": True}

        hooks = {
            "PreToolUse": [HookMatcher(matcher="Bash", hooks=[my_hook])],
        }
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            hooks=hooks,
        )
        assert opts.hooks is not None
        assert "PreToolUse" in opts.hooks
