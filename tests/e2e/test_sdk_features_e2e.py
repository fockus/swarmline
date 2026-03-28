"""E2E: full user flow with SDK 0.1.48 features. Tests verify full scenarios ispolzovaniya novyh fich cognitia:
1. Hook-based security guard -> blocks dangerous commands
2. In-process MCP tool -> used in runtime adapter flow
3. Structured output -> query returns structured result
4. Dynamic control -> model switching mid-session
5. Session resume/fork -> conversation continuity
6. File checkpointing -> rewind to checkpoint Vse tests ispolzuyut real komponotnty cognitia, mockaya tolko
ClaudeSDKClient (subprocess boundary).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
from cognitia.hooks.registry import HookRegistry
from cognitia.hooks.sdk_bridge import registry_to_sdk_hooks
from cognitia.runtime.adapter import (
    AssistantMessage,
    ResultMessage,
    RuntimeAdapter,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from cognitia.runtime.claude_code import ClaudeCodeRuntime
from cognitia.runtime.options_builder import ClaudeOptionsBuilder
from cognitia.runtime.sdk_query import one_shot_query
from cognitia.runtime.sdk_tools import create_mcp_server, mcp_tool
from cognitia.runtime.types import Message, RuntimeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_text_block(text: str) -> MagicMock:
    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def _mock_thinking_block(thinking: str = "thinking...") -> MagicMock:
    block = MagicMock(spec=ThinkingBlock)
    block.thinking = thinking
    block.signature = "sig"
    return block


def _mock_tool_use_block(name: str, input_data: dict[str, Any]) -> MagicMock:
    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.input = input_data
    block.id = "tu-1"
    return block


def _mock_tool_result_block(content: str) -> MagicMock:
    block = MagicMock(spec=ToolResultBlock)
    block.content = content
    return block


def _mock_assistant_msg(blocks: list) -> MagicMock:
    msg = MagicMock(spec=AssistantMessage)
    msg.content = blocks
    msg.model = "sonnet"
    return msg


def _mock_result_msg(
    session_id: str = "sess-e2e",
    cost: float = 0.05,
    usage: dict | None = None,
    structured_output: Any = None,
) -> MagicMock:
    msg = MagicMock(spec=ResultMessage)
    msg.session_id = session_id
    msg.total_cost_usd = cost
    msg.usage = usage or {"input_tokens": 100, "output_tokens": 50}
    msg.structured_output = structured_output
    msg.duration_ms = 1000
    msg.duration_api_ms = 900
    msg.num_turns = 1
    msg.is_error = False
    msg.result = None
    msg.subtype = "success"
    return msg


def _make_connected_adapter(fake_receive_response) -> RuntimeAdapter:
    """Create RuntimeAdapter with zamockannym client."""
    mock_client = AsyncMock()
    mock_client.receive_response = fake_receive_response
    mock_options = MagicMock()
    mock_options.stderr = None
    adapter = RuntimeAdapter(mock_options)
    adapter._client = mock_client
    return adapter


# ---------------------------------------------------------------------------
# E2E: Hook-based security guard
# ---------------------------------------------------------------------------


class TestE2EHookSecurityGuard:
    """Scenario: zaregister hook -> collect options -> run cherez runtime."""

    @pytest.mark.asyncio
    async def test_hook_blocks_dangerous_command_end_to_end(self) -> None:
        """Full tsikl: hook registration -> bridge -> options -> callback execution. Scenario: 1. User registers PreToolUse hook cherez HookRegistry 2. Bridge converts in SDK format 3. Options are assembled with hooks 4. Pri vyzove Bash with 'rm -rf' hook returns block """
        # Step 1: Register hook
        registry = HookRegistry()
        blocked_commands: list[str] = []

        async def security_guard(**kwargs: Any) -> dict[str, Any]:
            tool_input = kwargs.get("tool_input", {})
            command = tool_input.get("command", "")
            if "rm -rf" in command:
                blocked_commands.append(command)
                return {
                    "decision": "block",
                    "reason": "Destructive command blocked by security hook",
                }
            return {"continue_": True}

        registry.on_pre_tool_use(security_guard, matcher="Bash")

        # Step 2: Convert to SDK format
        sdk_hooks = registry_to_sdk_hooks(registry)
        assert sdk_hooks is not None

        # Step 3: Build options
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="You are a helpful assistant",
            hooks=sdk_hooks,
        )
        assert opts.hooks is not None

        # Step 4: Simulate SDK calling the hook
        sdk_callback = opts.hooks["PreToolUse"][0].hooks[0]

        # Safe command → allow
        result_safe = await sdk_callback(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "tool_use_id": "tu-1",
                "session_id": "s1",
                "transcript_path": "/tmp/t",
                "cwd": "/home",
            },
            "tu-1",
            {"signal": None},
        )
        assert result_safe.get("continue_") is True

        # Dangerous command → block
        result_danger = await sdk_callback(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
                "tool_use_id": "tu-2",
                "session_id": "s1",
                "transcript_path": "/tmp/t",
                "cwd": "/home",
            },
            "tu-2",
            {"signal": None},
        )
        assert result_danger["decision"] == "block"
        assert len(blocked_commands) == 1


# ---------------------------------------------------------------------------
# E2E: In-process MCP tool → full runtime flow
# ---------------------------------------------------------------------------


class TestE2EMcpToolFlow:
    """Scenario: create MCP tool -> collect options -> runtime strimit tool usage."""

    def test_mcp_tool_to_options_to_runtime_setup(self) -> None:
        """Full tsikl: @mcp_tool -> create_mcp_server -> options. Verifies chto in-process MCP tool pofails in options and mozhet byt ispolzovan runtime'om. """

        @mcp_tool(
            "calculate_goal", "Calculate financial goal plan", {"target": float, "years": int}
        )
        async def calculate_goal(args: dict[str, Any]) -> dict[str, Any]:
            target = args["target"]
            years = args["years"]
            monthly = target / (years * 12)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Monthly savings needed: {monthly:.2f}",
                    }
                ],
            }

        server = create_mcp_server("freedom_tools", tools=[calculate_goal])

        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="Financial coach",
            sdk_mcp_servers={"freedom": server},
            allowed_tools=["mcp__freedom__calculate_goal"],
        )

        assert "freedom" in opts.mcp_servers
        assert opts.mcp_servers["freedom"]["type"] == "sdk"
        assert "mcp__freedom__calculate_goal" in opts.allowed_tools

    @pytest.mark.asyncio
    async def test_mcp_tool_handler_execution(self) -> None:
        """MCP tool handler vyzyvaetsya and returns correct result."""

        @mcp_tool("assess_health", "Assess financial health", {"income": float, "expenses": float})
        async def assess_health(args: dict[str, Any]) -> dict[str, Any]:
            ratio = args["expenses"] / args["income"] if args["income"] > 0 else 1.0
            score = max(0, int((1 - ratio) * 100))
            return {
                "content": [{"type": "text", "text": f"Health score: {score}"}],
            }

        result = await assess_health.handler({"income": 100000, "expenses": 60000})
        assert result["content"][0]["text"] == "Health score: 40"


# ---------------------------------------------------------------------------
# E2E: Structured output flow
# ---------------------------------------------------------------------------


class TestE2EStructuredOutput:
    """Scenario: structured output -> query -> parse result."""

    @pytest.mark.asyncio
    async def test_structured_output_end_to_end(self) -> None:
        """Full tsikl: output_format in options -> ResultMessage.structured_output -> QueryResult."""
        structured_data = {"diagnosis": "healthy", "score": 85, "recommendations": ["save more"]}

        async def fake_query(**kwargs):
            yield _mock_assistant_msg([_mock_text_block("Analysis complete")])
            yield _mock_result_msg(structured_output=structured_data)

        with patch("cognitia.runtime.sdk_query._sdk_query", side_effect=fake_query):
            result = await one_shot_query(
                "Diagnose my finances",
                system_prompt="You are a financial analyst",
                model="sonnet",
                output_format={
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "diagnosis": {"type": "string"},
                            "score": {"type": "number"},
                            "recommendations": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            )

        assert result.text == "Analysis complete"
        assert result.structured_output is not None
        assert result.structured_output["diagnosis"] == "healthy"
        assert result.structured_output["score"] == 85
        assert "save more" in result.structured_output["recommendations"]


# ---------------------------------------------------------------------------
# E2E: Dynamic model switching mid-session
# ---------------------------------------------------------------------------


class TestE2EDynamicModelSwitch:
    """Scenario: nachat with sonnet -> esclalate to opus -> back to sonnet."""

    @pytest.mark.asyncio
    async def test_model_switch_during_session(self) -> None:
        """Full tsikl: connect -> query -> set_model -> query -> results."""
        mock_client = AsyncMock()
        set_model_calls: list[str] = []

        # Track set_model calls
        async def track_set_model(model):
            set_model_calls.append(model)

        mock_client.set_model = track_set_model

        call_count = 0

        async def fake_receive_response():
            nonlocal call_count
            call_count += 1
            yield _mock_assistant_msg([_mock_text_block(f"Response #{call_count}")])
            yield _mock_result_msg(session_id=f"sess-{call_count}")

        mock_client.receive_response = fake_receive_response

        # Setup adapter
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        # Turn 1: default model (sonnet)
        events_1 = []
        async for event in adapter.stream_reply("Simple question"):
            events_1.append(event)
        assert events_1[-1].text == "Response #1"
        assert events_1[-1].session_id == "sess-1"

        # Switch to opus
        await adapter.set_model("opus")

        # Turn 2: opus
        events_2 = []
        async for event in adapter.stream_reply("Complex strategy question"):
            events_2.append(event)
        assert events_2[-1].text == "Response #2"

        # Switch back to sonnet
        await adapter.set_model("sonnet")

        assert set_model_calls == ["opus", "sonnet"]


# ---------------------------------------------------------------------------
# E2E: Multi-turn with thinking + tools + metrics
# ---------------------------------------------------------------------------


class TestE2EMultiTurnWithMetrics:
    """Scenario: full multi-turn flow with thinking, tools and metricmi."""

    @pytest.mark.asyncio
    async def test_full_turn_with_thinking_tools_and_metrics(self) -> None:
        """Turn: thinking -> tool call -> tool result -> text -> metrics. Verifies ves pipeline cherez ClaudeCodeRuntime: 1. ThinkingBlock - logiruetsya, not strimitsya 2. ToolUseBlock -> tool_call_started event 3. ToolResultBlock -> tool_call_finished event 4. TextBlock -> assistant_delta event 5. ResultMessage -> metrics in final event """
        mock_client = AsyncMock()

        async def fake_receive_response():
            # Assistant thinks, uses tool, gets result, responds
            yield _mock_assistant_msg(
                [
                    _mock_thinking_block("Let me analyze the deposits..."),
                    _mock_tool_use_block("mcp__finuslugi__get_deposits", {"min_rate": 15}),
                    _mock_tool_result_block("Found 5 deposits with rate >= 15%"),
                    _mock_text_block("Я нашёл 5 вкладов с доходностью от 15%."),
                ]
            )
            yield _mock_result_msg(
                session_id="sess-deposits",
                cost=0.08,
                usage={"input_tokens": 500, "output_tokens": 200},
            )

        mock_client.receive_response = fake_receive_response
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        runtime = ClaudeCodeRuntime(
            config=RuntimeConfig(runtime_name="claude_sdk"),
            adapter=adapter,
        )

        messages = [Message(role="user", content="Найди вклады от 15%")]
        events = []
        async for event in runtime.run(
            messages=messages,
            system_prompt="Financial advisor",
            active_tools=[],
        ):
            events.append(event)

        # Verify event types
        event_types = [e.type for e in events]
        assert "tool_call_started" in event_types
        assert "tool_call_finished" in event_types
        assert "assistant_delta" in event_types
        assert "final" in event_types

        # ThinkingBlock should NOT appear as text
        text_events = [e for e in events if e.type == "assistant_delta"]
        assert len(text_events) == 1
        assert "Я нашёл 5 вкладов" in text_events[0].data["text"]

        # Final event
        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "Я нашёл 5 вкладов с доходностью от 15%."
        assert final.data["metrics"]["tool_calls_count"] == 1


# ---------------------------------------------------------------------------
# E2E: Session resume and fork
# ---------------------------------------------------------------------------


class TestE2ESessionManagement:
    """Scenario: session resume and fork cherez options."""

    def test_resume_session_options(self) -> None:
        """Options for resume sessions."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            resume="sess-previous-123",
            continue_conversation=True,
        )
        assert opts.resume == "sess-previous-123"
        assert opts.continue_conversation is True

    def test_fork_session_options(self) -> None:
        """Options for fork sessions (resume + fork)."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            resume="sess-previous-123",
            fork_session=True,
        )
        assert opts.resume == "sess-previous-123"
        assert opts.fork_session is True


# ---------------------------------------------------------------------------
# E2E: File checkpointing + rewind
# ---------------------------------------------------------------------------


class TestE2EFileCheckpointing:
    """Scenario: enable checkpointing -> get checkpoint -> rewind."""

    def test_checkpointing_options(self) -> None:
        """Options with file checkpointing."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="test",
            enable_file_checkpointing=True,
        )
        assert opts.enable_file_checkpointing is True

    @pytest.mark.asyncio
    async def test_rewind_files_flow(self) -> None:
        """Full flow: enable checkpointing -> query -> rewind."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _mock_assistant_msg([_mock_text_block("Made changes")])
            yield _mock_result_msg(session_id="sess-chk")

        mock_client.receive_response = fake_receive_response

        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        # Turn 1
        events = []
        async for event in adapter.stream_reply("Make some changes"):
            events.append(event)

        # Rewind to checkpoint
        await adapter.rewind_files("user-msg-uuid-1")
        mock_client.rewind_files.assert_awaited_once_with("user-msg-uuid-1")


# ---------------------------------------------------------------------------
# E2E: Budget and beta features
# ---------------------------------------------------------------------------


class TestE2EBudgetAndBeta:
    """Scenario: 1M context beta + budget limit."""

    def test_1m_context_with_budget(self) -> None:
        """Options with 1M context beta and budget."""
        builder = ClaudeOptionsBuilder()
        opts = builder.build(
            role_id="coach",
            system_prompt="Analyze this very long document...",
            betas=["context-1m-2025-08-07"],
            max_budget_usd=25.0,
            max_thinking_tokens=64000,
        )

        assert opts.betas == ["context-1m-2025-08-07"]
        assert opts.max_budget_usd == 25.0
        # max_thinking_tokens is deprecated; value goes to thinking config
        assert opts.thinking is not None
        assert opts.thinking["type"] == "enabled"
        assert opts.thinking["budget_tokens"] == 64000

    @pytest.mark.asyncio
    async def test_cost_tracking_through_full_pipeline(self) -> None:
        """Metrics stoimosti prohodyat cherez full pipeline."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _mock_assistant_msg([_mock_text_block("Done")])
            yield _mock_result_msg(
                cost=2.50,
                usage={"input_tokens": 100000, "output_tokens": 5000},
            )

        mock_client.receive_response = fake_receive_response
        mock_options = MagicMock()
        mock_options.stderr = None
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        events = []
        async for event in adapter.stream_reply("Process long document"):
            events.append(event)

        done = events[-1]
        assert done.total_cost_usd == 2.50
        assert done.usage["input_tokens"] == 100000
