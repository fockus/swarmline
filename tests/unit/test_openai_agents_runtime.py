"""Tests for OpenAI Agents Runtime - event mapper, tool bridge, registration."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from swarmline.runtime.openai_agents.event_mapper import map_run_error, map_stream_event
from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig
from swarmline.runtime.types import Message


# ---------------------------------------------------------------------------
# Helpers: fake OpenAI SDK event objects
# ---------------------------------------------------------------------------


@dataclass
class FakeRawItem:
    text: str = ""
    name: str = ""
    arguments: str = "{}"
    call_id: str = "call_123"
    output: str = ""


@dataclass
class FakeItem:
    raw_item: Any = None
    target_agent: Any = None


@dataclass
class FakeRunItemEvent:
    type: str = "run_item_stream_event"
    name: str = ""
    item: Any = None


@dataclass
class FakeAgentUpdatedEvent:
    type: str = "agent_updated_stream_event"
    new_agent: Any = None


@dataclass
class FakeRawDelta:
    type: str = "response.output_text.delta"
    delta: str = ""


@dataclass
class FakeRawResponseEvent:
    type: str = "raw_response_stream_event"
    data: Any = None


@dataclass
class FakeAgent:
    name: str = "test-agent"


# ---------------------------------------------------------------------------
# Event mapper tests
# ---------------------------------------------------------------------------


class TestEventMapper:
    """Tests for map_stream_event."""

    def test_message_output_created(self) -> None:
        """message_output_created maps to assistant_delta."""
        raw = FakeRawItem(text="Hello world")
        item = FakeItem(raw_item=raw)
        event = FakeRunItemEvent(name="message_output_created", item=item)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "assistant_delta"
        assert result.data["text"] == "Hello world"

    def test_tool_called(self) -> None:
        """tool_called maps to tool_call_started."""
        raw = FakeRawItem(name="codex", arguments='{"prompt": "test"}', call_id="c1")
        item = FakeItem(raw_item=raw)
        event = FakeRunItemEvent(name="tool_called", item=item)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "tool_call_started"
        assert result.data["name"] == "codex"
        assert result.data["correlation_id"] == "c1"

    def test_tool_output(self) -> None:
        """tool_output maps to tool_call_finished."""
        raw = FakeRawItem(output="done", call_id="c1")
        item = FakeItem(raw_item=raw)
        event = FakeRunItemEvent(name="tool_output", item=item)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "tool_call_finished"
        assert result.data["ok"] is True

    def test_handoff_requested(self) -> None:
        """handoff_requested maps to status."""
        agent = FakeAgent(name="coder")
        item = FakeItem(target_agent=agent)
        event = FakeRunItemEvent(name="handoff_requested", item=item)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "status"
        assert "coder" in result.data.get("text", "")

    def test_agent_updated(self) -> None:
        """AgentUpdatedStreamEvent maps to status."""
        agent = FakeAgent(name="reviewer")
        event = FakeAgentUpdatedEvent(new_agent=agent)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "status"
        assert "reviewer" in result.data.get("text", "")

    def test_raw_response_text_delta(self) -> None:
        """RawResponsesStreamEvent with text delta maps to assistant_delta."""
        delta = FakeRawDelta(delta="chunk")
        event = FakeRawResponseEvent(data=delta)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "assistant_delta"
        assert result.data["text"] == "chunk"

    def test_unknown_event_returns_none(self) -> None:
        """Unknown event types return None."""
        event = MagicMock()
        event.type = "some_unknown_type"
        result = map_stream_event(event)
        assert result is None

    def test_map_run_error(self) -> None:
        """map_run_error converts exception to error event."""
        result = map_run_error(ValueError("test error"))
        assert result.type == "error"
        assert "test error" in result.data.get("message", "")

    def test_map_run_error_redacts_secret(self) -> None:
        """OpenAI Agents SDK errors do not expose raw credentials."""
        secret = "sk-proj-openai-agents-secret-1234567890abcdef"
        result = map_run_error(RuntimeError(f"request failed: {secret}"))

        assert result.type == "error"
        assert secret not in result.data.get("message", "")
        assert "RuntimeError" in result.data.get("message", "")


# ---------------------------------------------------------------------------
# Types tests
# ---------------------------------------------------------------------------


class TestOpenAIAgentsConfig:
    """Tests for OpenAIAgentsConfig."""

    def test_defaults(self) -> None:
        """Default config values."""
        cfg = OpenAIAgentsConfig()
        assert cfg.model == "gpt-4.1"
        assert cfg.codex_enabled is False
        assert cfg.max_turns == 25

    def test_frozen(self) -> None:
        """Config is immutable."""
        cfg = OpenAIAgentsConfig()
        with pytest.raises(AttributeError):
            cfg.model = "other"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        """Custom config values."""
        cfg = OpenAIAgentsConfig(
            model="o3",
            codex_enabled=True,
            max_turns=10,
        )
        assert cfg.model == "o3"
        assert cfg.codex_enabled is True
        assert cfg.max_turns == 10


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestOpenAIAgentsRegistration:
    """Tests that openai_agents is properly registered."""

    def test_valid_runtime_name(self) -> None:
        """openai_agents is a valid runtime name."""
        from swarmline.runtime.capabilities import VALID_RUNTIME_NAMES

        assert "openai_agents" in VALID_RUNTIME_NAMES

    def test_capabilities_registered(self) -> None:
        """openai_agents has capabilities."""
        from swarmline.runtime.capabilities import get_runtime_capabilities

        caps = get_runtime_capabilities("openai_agents")
        assert caps.runtime_name == "openai_agents"
        assert caps.tier == "full"
        assert caps.supports_mcp is True

    def test_registry_has_factory(self) -> None:
        """openai_agents factory is in the default registry."""
        from swarmline.runtime.registry import (
            get_default_registry,
            reset_default_registry,
        )

        reset_default_registry()
        registry = get_default_registry()
        assert registry.is_registered("openai_agents")
        reset_default_registry()

    def test_agent_config_accepts_openai_agents(self) -> None:
        """AgentConfig validates openai_agents as a valid runtime."""
        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="test",
            runtime="openai_agents",
        )
        assert config.runtime == "openai_agents"


# ---------------------------------------------------------------------------
# Runtime unit tests (no real API calls)
# ---------------------------------------------------------------------------


class TestOpenAIAgentsRuntime:
    """Unit tests for OpenAIAgentsRuntime."""

    def test_extract_user_input(self) -> None:
        """Extracts last user message."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="first"),
            Message(role="assistant", content="response"),
            Message(role="user", content="second"),
        ]
        assert OpenAIAgentsRuntime._extract_user_input(messages) == "second"

    def test_extract_user_input_empty(self) -> None:
        """Returns empty string when no user messages."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [Message(role="system", content="sys")]
        assert OpenAIAgentsRuntime._extract_user_input(messages) == ""

    @pytest.mark.asyncio
    async def test_run_no_user_message_yields_error(self) -> None:
        """run() yields error when no user message in messages."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        rt = OpenAIAgentsRuntime()
        events = []
        async for event in rt.run(
            messages=[Message(role="system", content="sys")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"

    def test_cancel(self) -> None:
        """cancel() sets flag."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        rt = OpenAIAgentsRuntime()
        assert rt._cancel_requested is False
        rt.cancel()
        assert rt._cancel_requested is True

    @pytest.mark.asyncio
    async def test_cleanup(self) -> None:
        """cleanup() resets cancel flag."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        rt = OpenAIAgentsRuntime()
        rt.cancel()
        await rt.cleanup()
        assert rt._cancel_requested is False

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Context manager returns runtime and resets cancel on exit."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        async with OpenAIAgentsRuntime() as rt:
            assert isinstance(rt, OpenAIAgentsRuntime)
            rt.cancel()
            assert rt._cancel_requested is True
        assert rt._cancel_requested is False

    @pytest.mark.asyncio
    async def test_run_exception_redacts_secret_in_error_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runner exceptions are sanitized before RuntimeEvent.error."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        secret = "sk-proj-runner-secret-1234567890abcdef"

        class _Agent:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        class _Result:
            async def stream_events(self):
                raise RuntimeError(f"runner failed: {secret}")
                yield object()

        class _Runner:
            @staticmethod
            def run_streamed(**kwargs: Any) -> _Result:
                _ = kwargs
                return _Result()

        fake_agents = types.SimpleNamespace(Agent=_Agent, Runner=_Runner)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        rt = OpenAIAgentsRuntime()
        events = []
        async for event in rt.run(
            messages=[Message(role="user", content="hello")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        assert [event.type for event in events] == ["error"]
        assert secret not in events[0].data["message"]
        assert "RuntimeError" in events[0].data["message"]


# ---------------------------------------------------------------------------
# Tool bridge tests (S6)
# ---------------------------------------------------------------------------


class TestToolBridge:
    """Tests for tool_bridge.py."""

    def test_toolspecs_to_agent_tools_empty(self) -> None:
        """Empty list returns empty list."""
        from swarmline.runtime.openai_agents.tool_bridge import toolspecs_to_agent_tools

        assert toolspecs_to_agent_tools([]) == []

    def test_toolspecs_filters_non_local(self) -> None:
        """Only is_local=True tools are converted."""
        from swarmline.runtime.openai_agents.tool_bridge import toolspecs_to_agent_tools
        from swarmline.runtime.types import ToolSpec

        specs = [
            ToolSpec(
                name="remote_tool", description="Remote", parameters={}, is_local=False
            ),
            ToolSpec(
                name="local_tool", description="Local", parameters={}, is_local=True
            ),
        ]
        result = toolspecs_to_agent_tools(specs)
        assert len(result) == 1

    def test_toolspec_to_function_tool_with_executor(self) -> None:
        """Tool with executor calls the executor."""
        from swarmline.runtime.openai_agents.tool_bridge import (
            toolspec_to_function_tool,
        )
        from swarmline.runtime.types import ToolSpec

        calls: list[tuple[str, dict]] = []

        async def mock_executor(name: str, kwargs: dict) -> str:
            calls.append((name, kwargs))
            return '{"result": "ok"}'

        spec = ToolSpec(
            name="my_tool", description="Test", parameters={}, is_local=True
        )
        tool = toolspec_to_function_tool(spec, executor=mock_executor)
        assert tool is not None

    def test_toolspec_to_function_tool_no_executor(self) -> None:
        """Tool without executor returns error JSON."""
        from swarmline.runtime.openai_agents.tool_bridge import (
            toolspec_to_function_tool,
        )
        from swarmline.runtime.types import ToolSpec

        spec = ToolSpec(
            name="orphan", description="No exec", parameters={}, is_local=True
        )
        tool = toolspec_to_function_tool(spec, executor=None)
        assert tool is not None

    @pytest.mark.asyncio
    async def test_on_invoke_calls_executor(self) -> None:
        """_on_invoke delegates to executor and returns result."""
        from swarmline.runtime.openai_agents.tool_bridge import (
            toolspec_to_function_tool,
        )
        from swarmline.runtime.types import ToolSpec

        calls: list[tuple[str, dict]] = []

        async def mock_executor(name: str, kwargs: dict) -> str:
            calls.append((name, kwargs))
            return '{"result": "ok"}'

        spec = ToolSpec(
            name="calc", description="Calculator", parameters={}, is_local=True
        )
        tool = toolspec_to_function_tool(spec, executor=mock_executor)
        result = await tool.on_invoke_tool(None, '{"x": 1}')
        assert result == '{"result": "ok"}'
        assert calls == [("calc", {"x": 1})]

    @pytest.mark.asyncio
    async def test_on_invoke_invalid_json_returns_error(self) -> None:
        """_on_invoke with invalid JSON returns error instead of crashing."""
        from swarmline.runtime.openai_agents.tool_bridge import (
            toolspec_to_function_tool,
        )
        from swarmline.runtime.types import ToolSpec

        spec = ToolSpec(name="t", description="T", parameters={}, is_local=True)
        tool = toolspec_to_function_tool(spec, executor=None)
        result = await tool.on_invoke_tool(None, "{invalid json")
        assert "error" in result
        assert "Invalid JSON" in result

    @pytest.mark.asyncio
    async def test_on_invoke_no_executor_returns_error(self) -> None:
        """_on_invoke without executor returns error JSON."""
        from swarmline.runtime.openai_agents.tool_bridge import (
            toolspec_to_function_tool,
        )
        from swarmline.runtime.types import ToolSpec

        spec = ToolSpec(name="t", description="T", parameters={}, is_local=True)
        tool = toolspec_to_function_tool(spec, executor=None)
        result = await tool.on_invoke_tool(None, "{}")
        assert "error" in result
        assert "No executor" in result

    @pytest.mark.asyncio
    async def test_build_tool_executor_calls_swarmline_handler(self) -> None:
        from swarmline.runtime.openai_agents.tool_bridge import build_tool_executor

        async def calc(x: int) -> int:
            return x + 1

        executor = build_tool_executor({"calc": calc})

        result = await executor("calc", {"x": 41})

        assert result == "42"

    @pytest.mark.asyncio
    async def test_build_tool_executor_unknown_tool_fails_fast(self) -> None:
        from swarmline.runtime.openai_agents.tool_bridge import build_tool_executor

        executor = build_tool_executor({})

        result = await executor("missing", {})

        assert "Unknown local tool" in result


# ---------------------------------------------------------------------------
# Multi-turn input tests
# ---------------------------------------------------------------------------


class TestBuildInput:
    """Tests for _build_input multi-turn message handling."""

    def test_single_user_message_returns_string(self) -> None:
        """Single user message returns plain string."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [Message(role="user", content="hello")]
        result = OpenAIAgentsRuntime._build_input(messages)
        assert result == "hello"

    def test_multi_turn_returns_list(self) -> None:
        """Multi-turn conversation returns list of dicts."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [
            Message(role="user", content="first"),
            Message(role="assistant", content="reply"),
            Message(role="user", content="second"),
        ]
        result = OpenAIAgentsRuntime._build_input(messages)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == {"role": "user", "content": "first"}
        assert result[2] == {"role": "user", "content": "second"}

    def test_system_messages_excluded(self) -> None:
        """System messages are skipped (Agent.instructions handles them)."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [
            Message(role="system", content="sys prompt"),
            Message(role="user", content="query"),
        ]
        result = OpenAIAgentsRuntime._build_input(messages)
        assert result == "query"

    def test_no_user_messages_returns_empty(self) -> None:
        """No user messages returns empty string."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [Message(role="system", content="sys")]
        result = OpenAIAgentsRuntime._build_input(messages)
        assert result == ""

    def test_legacy_extract_still_works(self) -> None:
        """_extract_user_input (deprecated) still works."""
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        messages = [
            Message(role="user", content="first"),
            Message(role="user", content="last"),
        ]
        assert OpenAIAgentsRuntime._extract_user_input(messages) == "last"


class TestOpenAIAgentsFactory:
    def test_factory_passes_tool_executors_to_runtime(self) -> None:
        from swarmline.runtime.registry import _create_openai_agents
        from swarmline.runtime.types import RuntimeConfig

        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)

        handler = MagicMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "swarmline.runtime.openai_agents.runtime.OpenAIAgentsRuntime", fake_cls
            )
            runtime = _create_openai_agents(
                RuntimeConfig(runtime_name="openai_agents"),
                tool_executors={"calc": handler},
            )

        assert runtime is fake_runtime
        assert fake_cls.call_args.kwargs["tool_executor"] is not None

    def test_factory_rejects_mcp_servers_until_bridge_is_implemented(self) -> None:
        from swarmline.runtime.registry import _create_openai_agents
        from swarmline.runtime.types import RuntimeConfig

        with pytest.raises(ValueError, match="mcp_servers"):
            _create_openai_agents(
                RuntimeConfig(runtime_name="openai_agents"),
                mcp_servers={"srv": "https://mcp.test"},
            )
