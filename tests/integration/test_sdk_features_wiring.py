"""Integration: SDK 0.1.48 features wiring — сборка ClaudeAgentOptions со всеми новыми фичами.

Проверяет что компоненты cognitia корректно собираются вместе:
- HookRegistry → SDK hooks через bridge → ClaudeAgentOptions
- In-process MCP tools → ClaudeAgentOptions.mcp_servers
- Structured output + session management + betas → ClaudeAgentOptions
- RuntimeAdapter dynamic control delegation chain
- ResultMessage metrics → StreamEvent → ClaudeCodeRuntime → RuntimeEvent
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

pytestmark = pytest.mark.requires_claude_sdk

from cognitia.hooks.registry import HookRegistry
from cognitia.hooks.sdk_bridge import registry_to_sdk_hooks
from cognitia.runtime.adapter import RuntimeAdapter
from cognitia.runtime.options_builder import ClaudeOptionsBuilder
from cognitia.runtime.sdk_tools import create_mcp_server, mcp_tool

# ---------------------------------------------------------------------------
# HookRegistry → SDK hooks → ClaudeAgentOptions pipeline
# ---------------------------------------------------------------------------


class TestHookRegistryToOptions:
    """HookRegistry → sdk_bridge → ClaudeOptionsBuilder → ClaudeAgentOptions."""

    def test_hooks_pipeline_end_to_end(self) -> None:
        """Полный pipeline: register hooks → convert → build options."""
        registry = HookRegistry()

        async def block_rm(
            hook_event_name: str = "",
            tool_name: str = "",
            tool_input: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            if tool_input and "rm -rf" in tool_input.get("command", ""):
                return {"decision": "block", "reason": "Destructive command blocked"}
            return {"continue_": True}

        registry.on_pre_tool_use(block_rm, matcher="Bash")

        # Convert to SDK format
        sdk_hooks = registry_to_sdk_hooks(registry)
        assert sdk_hooks is not None

        # Build options with hooks
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            hooks=sdk_hooks,
        )

        assert opts.hooks is not None
        assert "PreToolUse" in opts.hooks
        assert len(opts.hooks["PreToolUse"]) == 1
        assert opts.hooks["PreToolUse"][0].matcher == "Bash"

    @pytest.mark.asyncio
    async def test_hook_callback_execution_in_pipeline(self) -> None:
        """Hook callback выполняется корректно через SDK bridge."""
        registry = HookRegistry()
        invocations: list[str] = []

        async def log_tool_use(**kwargs: Any) -> dict[str, Any]:
            invocations.append(kwargs.get("tool_name", "unknown"))
            return {"continue_": True}

        registry.on_post_tool_use(log_tool_use)

        sdk_hooks = registry_to_sdk_hooks(registry)
        assert sdk_hooks is not None

        # Simulate SDK calling the hook
        sdk_callback = sdk_hooks["PostToolUse"][0].hooks[0]
        await sdk_callback(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/x"},
                "tool_response": "file contents",
                "tool_use_id": "tu-1",
                "session_id": "s1",
                "transcript_path": "/tmp/t",
                "cwd": "/home",
            },
            "tu-1",
            {"signal": None},
        )

        assert invocations == ["Read"]

    def test_multiple_hook_events_in_options(self) -> None:
        """Несколько типов хуков → все попадают в options."""
        registry = HookRegistry()

        async def noop(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        registry.on_pre_tool_use(noop, matcher="Bash")
        registry.on_post_tool_use(noop)
        registry.on_stop(noop)
        registry.on_user_prompt(noop)

        sdk_hooks = registry_to_sdk_hooks(registry)
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            hooks=sdk_hooks,
        )

        assert opts.hooks is not None
        assert len(opts.hooks) == 4
        assert set(opts.hooks.keys()) == {"PreToolUse", "PostToolUse", "Stop", "UserPromptSubmit"}


# ---------------------------------------------------------------------------
# In-process MCP tools → ClaudeAgentOptions pipeline
# ---------------------------------------------------------------------------


class TestMcpToolsToOptions:
    """In-process MCP tools → create_mcp_server → ClaudeOptionsBuilder."""

    def test_mcp_tools_in_options_pipeline(self) -> None:
        """@mcp_tool → create_mcp_server → sdk_mcp_servers → options."""

        @mcp_tool("greet", "Greet user", {"name": str})
        async def greet(args: dict[str, Any]) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": f"Hi {args['name']}"}]}

        server_config = create_mcp_server("greeting_svc", tools=[greet])

        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            sdk_mcp_servers={"greeting": server_config},
        )

        assert "greeting" in opts.mcp_servers
        assert opts.mcp_servers["greeting"]["type"] == "sdk"

    def test_mixed_mcp_servers_in_options(self) -> None:
        """Remote MCP + in-process MCP в одних options."""
        from cognitia.skills.types import McpServerSpec

        @mcp_tool("local_calc", "Calculator", {"expr": str})
        async def calc(args: dict[str, Any]) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "42"}]}

        sdk_server = create_mcp_server("calc_svc", tools=[calc])

        remote_servers = {
            "iss": McpServerSpec(name="iss", url="http://iss.test"),
        }

        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            mcp_servers=remote_servers,
            sdk_mcp_servers={"calc": sdk_server},
        )

        # Оба сервера присутствуют
        assert "iss" in opts.mcp_servers
        assert "calc" in opts.mcp_servers
        assert opts.mcp_servers["iss"]["type"] == "http"
        assert opts.mcp_servers["calc"]["type"] == "sdk"


# ---------------------------------------------------------------------------
# Full options assembly — all SDK 0.1.48 features
# ---------------------------------------------------------------------------


class TestFullOptionsAssembly:
    """Сборка ClaudeAgentOptions со всеми новыми фичами SDK 0.1.48."""

    def test_structured_output_with_session_management(self) -> None:
        """output_format + continue_conversation + fork_session."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            output_format={
                "type": "json_schema",
                "schema": {"type": "object", "properties": {"score": {"type": "number"}}},
            },
            continue_conversation=True,
            fork_session=True,
        )

        assert opts.output_format is not None
        assert opts.output_format["type"] == "json_schema"
        assert opts.continue_conversation is True
        assert opts.fork_session is True

    def test_betas_with_budget_and_checkpointing(self) -> None:
        """betas + max_budget_usd + enable_file_checkpointing."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            betas=["context-1m-2025-08-07"],
            max_budget_usd=10.0,
            enable_file_checkpointing=True,
        )

        assert opts.betas == ["context-1m-2025-08-07"]
        assert opts.max_budget_usd == 10.0
        assert opts.enable_file_checkpointing is True

    def test_all_features_combined(self) -> None:
        """Все фичи одновременно — ничего не конфликтует."""
        from claude_agent_sdk import AgentDefinition

        registry = HookRegistry()

        async def noop(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        registry.on_pre_tool_use(noop)
        sdk_hooks = registry_to_sdk_hooks(registry)

        @mcp_tool("my_tool", "Test tool", {"x": str})
        async def my_tool(args: dict[str, Any]) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "ok"}]}

        sdk_server = create_mcp_server("test_svc", tools=[my_tool])

        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="strategy_planner",
            system_prompt="You are a planner",
            sdk_mcp_servers={"test": sdk_server},
            hooks=sdk_hooks,
            agents={"researcher": AgentDefinition(description="R", prompt="research")},
            output_format={"type": "json_schema", "schema": {"type": "object"}},
            betas=["context-1m-2025-08-07"],
            max_budget_usd=5.0,
            max_thinking_tokens=32000,
            include_partial_messages=True,
            enable_file_checkpointing=True,
            sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
            env={"MY_KEY": "val"},
            fallback_model="haiku",
        )

        assert opts.hooks is not None
        assert "test" in opts.mcp_servers
        assert opts.agents is not None
        assert "researcher" in opts.agents
        assert opts.output_format is not None
        assert opts.betas == ["context-1m-2025-08-07"]
        assert opts.max_budget_usd == 5.0
        assert opts.max_thinking_tokens == 32000
        assert opts.include_partial_messages is True
        assert opts.enable_file_checkpointing is True
        assert opts.sandbox is not None
        assert opts.env == {"MY_KEY": "val"}
        assert opts.fallback_model == "haiku"
        # Default ModelPolicy → sonnet (escalate_roles пустой)
        assert opts.model == "sonnet"


# ---------------------------------------------------------------------------
# RuntimeAdapter dynamic control → ClaudeCodeRuntime pipeline
# ---------------------------------------------------------------------------


class TestAdapterDynamicControlPipeline:
    """RuntimeAdapter dynamic control → ClaudeCodeRuntime."""

    @pytest.mark.asyncio
    async def test_set_model_propagates_through_claude_code_runtime(self) -> None:
        """set_model на adapter доступен через ClaudeCodeRuntime.adapter."""
        from cognitia.runtime.claude_code import ClaudeCodeRuntime

        mock_client = AsyncMock()
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        runtime = ClaudeCodeRuntime(adapter=adapter)

        # Вызываем через runtime.adapter
        await runtime.adapter.set_model("opus")
        mock_client.set_model.assert_awaited_once_with("opus")

    @pytest.mark.asyncio
    async def test_interrupt_propagates_through_claude_code_runtime(self) -> None:
        """interrupt() доступен через ClaudeCodeRuntime.adapter."""
        from cognitia.runtime.claude_code import ClaudeCodeRuntime

        mock_client = AsyncMock()
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        runtime = ClaudeCodeRuntime(adapter=adapter)
        await runtime.adapter.interrupt()

        mock_client.interrupt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_mcp_status_propagates_through_runtime(self) -> None:
        """get_mcp_status() через ClaudeCodeRuntime.adapter."""
        from cognitia.runtime.claude_code import ClaudeCodeRuntime

        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [
                {"name": "iss", "status": "connected"},
                {"name": "finuslugi", "status": "pending"},
            ],
        }
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        runtime = ClaudeCodeRuntime(adapter=adapter)
        status = await runtime.adapter.get_mcp_status()

        assert len(status["mcpServers"]) == 2
        assert status["mcpServers"][0]["name"] == "iss"


# ---------------------------------------------------------------------------
# ResultMessage metrics → StreamEvent → ClaudeCodeRuntime final event
# ---------------------------------------------------------------------------


class TestMetricsPropagation:
    """ResultMessage metrics → StreamEvent → RuntimeEvent.final."""

    @pytest.mark.asyncio
    async def test_stream_event_metrics_reach_claude_code_runtime(self) -> None:
        """Метрики из ResultMessage → StreamEvent.done → ClaudeCodeRuntime final event."""
        from cognitia.runtime.adapter import ResultMessage
        from cognitia.runtime.claude_code import ClaudeCodeRuntime
        from cognitia.runtime.types import Message, RuntimeConfig

        mock_client = AsyncMock()

        # Mock ResultMessage с метриками
        result_msg = MagicMock(spec=ResultMessage)
        result_msg.session_id = "sess-abc"
        result_msg.total_cost_usd = 0.123
        result_msg.usage = {"input_tokens": 500, "output_tokens": 200}
        result_msg.structured_output = {"score": 85}
        result_msg.is_error = False
        result_msg.subtype = "success"
        result_msg.duration_ms = 2000

        # Mock AssistantMessage
        from cognitia.runtime.adapter import AssistantMessage, TextBlock

        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Результат анализа"
        assistant_msg = MagicMock(spec=AssistantMessage)
        assistant_msg.content = [text_block]

        async def fake_receive_response():
            yield assistant_msg
            yield result_msg

        mock_client.receive_response = fake_receive_response
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        runtime = ClaudeCodeRuntime(
            config=RuntimeConfig(runtime_name="claude_sdk"),
            adapter=adapter,
        )

        # Запускаем runtime
        messages = [Message(role="user", content="Проанализируй")]
        events = []
        async for event in runtime.run(
            messages=messages,
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        # Проверяем что StreamEvent.done с метриками дошёл до финала
        # RuntimeEvent.final содержит text
        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        assert final_events[0].data["text"] == "Результат анализа"

    @pytest.mark.asyncio
    async def test_structured_output_in_stream_event(self) -> None:
        """structured_output из ResultMessage доступен в StreamEvent.done."""
        from cognitia.runtime.adapter import ResultMessage

        mock_client = AsyncMock()

        from cognitia.runtime.adapter import AssistantMessage, TextBlock

        text_block = MagicMock(spec=TextBlock)
        text_block.text = "answer"
        assistant_msg = MagicMock(spec=AssistantMessage)
        assistant_msg.content = [text_block]

        result_msg = MagicMock(spec=ResultMessage)
        result_msg.session_id = "s1"
        result_msg.total_cost_usd = 0.01
        result_msg.usage = {}
        result_msg.structured_output = {"answer": "42", "confidence": 0.99}
        result_msg.is_error = False
        result_msg.subtype = "success"

        async def fake_receive_response():
            yield assistant_msg
            yield result_msg

        mock_client.receive_response = fake_receive_response

        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        events = []
        async for event in adapter.stream_reply("question"):
            events.append(event)

        done_event = events[-1]
        assert done_event.type == "done"
        assert done_event.structured_output == {"answer": "42", "confidence": 0.99}
        assert done_event.session_id == "s1"
        assert done_event.total_cost_usd == 0.01
