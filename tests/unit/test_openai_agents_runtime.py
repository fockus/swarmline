"""Tests for OpenAI Agents Runtime - event mapper, tool bridge, registration."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

_AGENTS_AVAILABLE = importlib.util.find_spec("agents") is not None

from swarmline.runtime.openai_agents.event_mapper import (  # noqa: E402
    StreamEventMapper,
    map_run_error,
    map_stream_event,
)
from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig  # noqa: E402
from swarmline.runtime.types import Message  # noqa: E402


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

    def test_tool_output_carries_tool_name_via_stateful_mapper(self) -> None:
        """tool_call_finished carries the tool name recorded at tool_called."""
        mapper = StreamEventMapper()
        called = FakeRunItemEvent(
            name="tool_called",
            item=FakeItem(raw_item=FakeRawItem(name="calc", call_id="c7")),
        )
        finished = FakeRunItemEvent(
            name="tool_output",
            item=FakeItem(raw_item=FakeRawItem(output="42", call_id="c7")),
        )

        mapper.map_event(called)
        result = mapper.map_event(finished)
        assert result is not None
        assert result.type == "tool_call_finished"
        assert result.data["name"] == "calc"
        assert result.data["correlation_id"] == "c7"
        assert result.data["ok"] is True

    def test_tool_output_error_contract_sets_ok_false(self) -> None:
        """Bridge error JSON ({"error": ...}) surfaces as ok=False."""
        raw = FakeRawItem(output='{"error": "boom"}', call_id="c1")
        event = FakeRunItemEvent(name="tool_output", item=FakeItem(raw_item=raw))

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "tool_call_finished"
        assert result.data["ok"] is False

    def test_tool_output_plain_json_is_not_error(self) -> None:
        raw = FakeRawItem(output='{"result": 4}', call_id="c1")
        event = FakeRunItemEvent(name="tool_output", item=FakeItem(raw_item=raw))

        result = map_stream_event(event)
        assert result is not None
        assert result.data["ok"] is True

    def test_raw_reasoning_delta_maps_to_thinking_delta(self) -> None:
        data = FakeRawDelta(
            type="response.reasoning_summary_text.delta", delta="Думаю..."
        )
        event = FakeRawResponseEvent(data=data)

        result = map_stream_event(event)
        assert result is not None
        assert result.type == "thinking_delta"
        assert result.data["text"] == "Думаю..."

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
        assert caps.level("mcp") == "native"
        assert caps.level("interrupt") == "emulated"
        assert caps.level("provider_override") == "native"
        assert caps.level("structured_output") == "native"
        assert caps.level("usage_reporting") == "native"

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


@pytest.mark.skipif(
    not _AGENTS_AVAILABLE,
    reason="openai-agents not installed (pip install swarmline[openai-agents])",
)
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

    def test_factory_passes_mcp_servers_to_runtime(self) -> None:
        """B2: mcp_servers reach OpenAIAgentsRuntime instead of raising."""
        from swarmline.runtime.registry import _create_openai_agents
        from swarmline.runtime.types import RuntimeConfig

        runtime = _create_openai_agents(
            RuntimeConfig(runtime_name="openai_agents"),
            mcp_servers={"srv": "https://mcp.test"},
        )
        assert runtime._mcp_servers == {"srv": "https://mcp.test"}

    def test_wiring_treats_openai_agents_as_portable_mcp_runtime(self) -> None:
        """B2: runtime_wiring passes mcp_servers through the portable path."""
        from swarmline.agent.runtime_wiring import (
            _FAIL_FAST_MCP_RUNTIMES,
            _PORTABLE_MCP_RUNTIMES,
        )

        assert "openai_agents" in _PORTABLE_MCP_RUNTIMES
        assert "openai_agents" not in _FAIL_FAST_MCP_RUNTIMES


# ---------------------------------------------------------------------------
# Fake agents SDK for run() tests (B1/B2/D1/D2)
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeChatModel:
    """Stand-in for agents.OpenAIChatCompletionsModel."""

    def __init__(self, model: str, openai_client: Any) -> None:
        self.model = model
        self.openai_client = openai_client


class _FakeStreamResult:
    def __init__(
        self,
        events: list[Any] | None = None,
        final_output: Any = None,
        usage: Any = None,
    ) -> None:
        self._events = list(events or [])
        self.final_output = final_output
        self.context_wrapper = types.SimpleNamespace(usage=usage)

    async def stream_events(self):
        for event in self._events:
            yield event


class _FakeModelSettings:
    """Stand-in for agents.ModelSettings (finding 3: thinking -> reasoning)."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> Any:
        return self.kwargs.get(name)


def _make_fake_agents_module(
    result: _FakeStreamResult,
    runner_calls: list[dict[str, Any]],
) -> types.SimpleNamespace:
    class _Runner:
        @staticmethod
        def run_streamed(**kwargs: Any) -> _FakeStreamResult:
            runner_calls.append(kwargs)
            return result

    return types.SimpleNamespace(
        Agent=_FakeAgent,
        Runner=_Runner,
        OpenAIChatCompletionsModel=_FakeChatModel,
        ModelSettings=_FakeModelSettings,
    )


async def _collect_events(rt: Any, **overrides: Any) -> list[Any]:
    kwargs: dict[str, Any] = {
        "messages": [Message(role="user", content="hello")],
        "system_prompt": "test",
        "active_tools": [],
    }
    kwargs.update(overrides)
    return [event async for event in rt.run(**kwargs)]


# ---------------------------------------------------------------------------
# B1: provider override tests
# ---------------------------------------------------------------------------


class TestProviderOverride:
    """RuntimeConfig.base_url/api_key and provider:model slugs are honored."""

    @pytest.mark.asyncio
    async def test_base_url_and_api_key_wrap_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents",
            model="gpt-4o-mini",
            base_url="https://proxy.test/v1",
            api_key="sk-test-override",
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        agent = runner_calls[0]["starting_agent"]
        model = agent.kwargs["model"]
        assert isinstance(model, _FakeChatModel)
        assert model.model == "gpt-4o-mini"
        assert model.openai_client.api_key == "sk-test-override"
        assert str(model.openai_client.base_url).startswith("https://proxy.test/v1")

    @pytest.mark.asyncio
    async def test_provider_slug_resolves_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents",
            model="openrouter:qwen/qwen-2.5-72b-instruct",
            api_key="sk-or-test",
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        model = runner_calls[0]["starting_agent"].kwargs["model"]
        assert isinstance(model, _FakeChatModel)
        assert model.model == "qwen/qwen-2.5-72b-instruct"
        assert "openrouter.ai" in str(model.openai_client.base_url)
        assert model.openai_client.api_key == "sk-or-test"

    @pytest.mark.asyncio
    async def test_provider_slug_uses_env_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-env")

        config = RuntimeConfig(
            runtime_name="openai_agents",
            model="deepseek:deepseek-chat",
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        model = runner_calls[0]["starting_agent"].kwargs["model"]
        assert model.openai_client.api_key == "sk-deepseek-env"
        assert "deepseek.com" in str(model.openai_client.base_url)

    @pytest.mark.asyncio
    async def test_anthropic_slug_yields_capability_unsupported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents",
            model="anthropic:claude-sonnet-4-20250514",
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert [event.type for event in events] == ["error"]
        assert events[0].data["kind"] == "capability_unsupported"
        assert "anthropic" in events[0].data["message"]
        assert runner_calls == []

    @pytest.mark.asyncio
    async def test_plain_model_without_override_passes_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        assert runner_calls[0]["starting_agent"].kwargs["model"] == "gpt-4.1"


# ---------------------------------------------------------------------------
# B2: generic MCP bridge tests
# ---------------------------------------------------------------------------


class _FakeMcpServer:
    """Base fake for agents.mcp server classes with connect/cleanup tracking."""

    lifecycle: list[str] = []

    def __init__(self, name: str, params: Any, **kwargs: Any) -> None:
        self.name = name
        self.params = params
        self.kwargs = kwargs

    async def connect(self) -> None:
        type(self).lifecycle.append(f"connect:{self.name}")

    async def cleanup(self) -> None:
        type(self).lifecycle.append(f"cleanup:{self.name}")


def _make_fake_mcp_module() -> tuple[types.SimpleNamespace, list[str]]:
    lifecycle: list[str] = []

    class _Stdio(_FakeMcpServer):
        pass

    class _Sse(_FakeMcpServer):
        pass

    class _Http(_FakeMcpServer):
        pass

    for cls in (_Stdio, _Sse, _Http):
        cls.lifecycle = lifecycle

    module = types.SimpleNamespace(
        MCPServerStdio=_Stdio,
        MCPServerSse=_Sse,
        MCPServerStreamableHttp=_Http,
    )
    return module, lifecycle


class TestGenericMcp:
    """Swarmline MCP specs map to SDK MCP servers with connect/cleanup lifecycle."""

    @pytest.mark.asyncio
    async def test_stdio_spec_maps_to_mcp_server_stdio(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        fake_mcp, lifecycle = _make_fake_mcp_module()
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setitem(sys.modules, "agents.mcp", fake_mcp)

        rt = OpenAIAgentsRuntime(
            mcp_servers={
                "files": {"command": "npx", "args": ["-y", "srv"], "env": {"A": "B"}}
            }
        )
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        servers = runner_calls[0]["starting_agent"].kwargs["mcp_servers"]
        assert len(servers) == 1
        assert isinstance(servers[0], fake_mcp.MCPServerStdio)
        assert servers[0].params == {
            "command": "npx",
            "args": ["-y", "srv"],
            "env": {"A": "B"},
        }
        assert lifecycle == ["connect:files", "cleanup:files"]

    @pytest.mark.asyncio
    async def test_http_sse_and_bare_url_specs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        fake_mcp, _lifecycle = _make_fake_mcp_module()
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setitem(sys.modules, "agents.mcp", fake_mcp)

        rt = OpenAIAgentsRuntime(
            mcp_servers={
                "http_srv": {"type": "http", "url": "https://mcp.test/http"},
                "sse_srv": {"type": "sse", "url": "https://mcp.test/sse"},
                "bare": "https://mcp.test/bare",
            }
        )
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        servers = runner_calls[0]["starting_agent"].kwargs["mcp_servers"]
        by_name = {server.name: server for server in servers}
        assert isinstance(by_name["http_srv"], fake_mcp.MCPServerStreamableHttp)
        assert isinstance(by_name["sse_srv"], fake_mcp.MCPServerSse)
        assert isinstance(by_name["bare"], fake_mcp.MCPServerStreamableHttp)
        assert by_name["sse_srv"].params == {"url": "https://mcp.test/sse"}

    @pytest.mark.asyncio
    async def test_unsafe_insecure_url_yields_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        fake_mcp, _lifecycle = _make_fake_mcp_module()
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setitem(sys.modules, "agents.mcp", fake_mcp)

        rt = OpenAIAgentsRuntime(mcp_servers={"bad": {"url": "http://mcp.test"}})
        events = await _collect_events(rt)

        assert [event.type for event in events] == ["error"]
        assert "Unsafe MCP server URL" in events[0].data["message"]
        assert runner_calls == []

    @pytest.mark.asyncio
    async def test_spec_without_command_or_url_yields_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        fake_mcp, _lifecycle = _make_fake_mcp_module()
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setitem(sys.modules, "agents.mcp", fake_mcp)

        rt = OpenAIAgentsRuntime(mcp_servers={"empty": {}})
        events = await _collect_events(rt)

        assert [event.type for event in events] == ["error"]
        assert "must define 'command'" in events[0].data["message"]
        assert runner_calls == []

    @pytest.mark.asyncio
    async def test_connect_failure_yields_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        fake_mcp, _lifecycle = _make_fake_mcp_module()

        async def _boom(self: Any) -> None:
            raise RuntimeError("connection refused")

        fake_mcp.MCPServerStreamableHttp.connect = _boom
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setitem(sys.modules, "agents.mcp", fake_mcp)

        rt = OpenAIAgentsRuntime(mcp_servers={"srv": "https://mcp.test"})
        events = await _collect_events(rt)

        assert [event.type for event in events] == ["error"]
        assert "Failed to connect MCP server" in events[0].data["message"]
        assert runner_calls == []


# ---------------------------------------------------------------------------
# D1: structured output tests
# ---------------------------------------------------------------------------


class TestStructuredOutput:
    """output_type/output_format are honored and structured_output lands in final."""

    @pytest.mark.asyncio
    async def test_output_type_passed_natively_and_final_output_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        class Answer(BaseModel):
            value: int

        answer = Answer(value=7)
        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(
            _FakeStreamResult(final_output=answer), runner_calls
        )
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents", model="gpt-4.1", output_type=Answer
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        final = events[-1]
        assert final.type == "final"
        assert final.data["structured_output"] is answer
        assert runner_calls[0]["starting_agent"].kwargs["output_type"] is Answer

    @pytest.mark.asyncio
    async def test_output_format_falls_back_to_prompt_and_parses_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        delta = FakeRawDelta(delta='{"a": 1}')
        event = FakeRawResponseEvent(data=delta)
        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(
            _FakeStreamResult(events=[event]), runner_calls
        )
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        config = RuntimeConfig(
            runtime_name="openai_agents", model="gpt-4.1", output_format=schema
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        final = events[-1]
        assert final.type == "final"
        assert final.data["structured_output"] == {"a": 1}
        instructions = runner_calls[0]["starting_agent"].kwargs["instructions"]
        assert "Structured output" in instructions
        assert '"properties"' in instructions
        # output_type must NOT be forced when only a schema dict is given
        assert "output_type" not in runner_calls[0]["starting_agent"].kwargs

    @pytest.mark.asyncio
    async def test_output_type_falls_back_to_text_parsing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        class Answer(BaseModel):
            value: int

        delta = FakeRawDelta(delta='{"value": 42}')
        event = FakeRawResponseEvent(data=delta)
        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(
            _FakeStreamResult(events=[event], final_output=None), runner_calls
        )
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents", model="gpt-4.1", output_type=Answer
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        final = events[-1]
        assert final.type == "final"
        assert isinstance(final.data["structured_output"], Answer)
        assert final.data["structured_output"].value == 42


# ---------------------------------------------------------------------------
# D2: usage reporting tests
# ---------------------------------------------------------------------------


class TestUsageReporting:
    """context_wrapper.usage populates TurnMetrics and final usage payload."""

    @pytest.mark.asyncio
    async def test_usage_populates_metrics_and_final_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        usage = types.SimpleNamespace(
            input_tokens=11, output_tokens=7, total_tokens=18, requests=2
        )
        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(
            _FakeStreamResult(usage=usage), runner_calls
        )
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        final = events[-1]
        assert final.type == "final"
        assert final.data["usage"] == {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "requests": 2,
        }
        assert final.data["metrics"]["tokens_in"] == 11
        assert final.data["metrics"]["tokens_out"] == 7
        assert final.data["metrics"]["model"] == "gpt-4.1"

    @pytest.mark.asyncio
    async def test_missing_usage_is_defensive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        final = events[-1]
        assert final.type == "final"
        assert "usage" not in final.data
        assert final.data["metrics"]["tokens_in"] == 0
        assert final.data["metrics"]["tokens_out"] == 0


# ---------------------------------------------------------------------------
# I-098a fix round (finding 3) — RuntimeConfig.thinking -> reasoning effort.
# Mirrors pi_sdk._thinking_level_from_runtime_config's thresholds.
# ---------------------------------------------------------------------------


class TestThinkingToReasoningEffort:
    """RuntimeConfig.thinking must reach agent_kwargs as model_settings.reasoning."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("budget_tokens", "expected_effort"),
        [(1024, "low"), (8000, "medium"), (32000, "high")],
    )
    async def test_thinking_budget_maps_to_reasoning_effort(
        self,
        monkeypatch: pytest.MonkeyPatch,
        budget_tokens: int,
        expected_effort: str,
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig, ThinkingConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(
            runtime_name="openai_agents",
            model="gpt-4.1",
            thinking=ThinkingConfig(budget_tokens=budget_tokens),
        )
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        agent_kwargs = runner_calls[0]["starting_agent"].kwargs
        assert "model_settings" in agent_kwargs
        model_settings = agent_kwargs["model_settings"]
        assert model_settings.kwargs["reasoning"].effort == expected_effort

    @pytest.mark.asyncio
    async def test_no_thinking_omits_model_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
        from swarmline.runtime.types import RuntimeConfig

        runner_calls: list[dict[str, Any]] = []
        fake_agents = _make_fake_agents_module(_FakeStreamResult(), runner_calls)
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        config = RuntimeConfig(runtime_name="openai_agents", model="gpt-4.1")
        rt = OpenAIAgentsRuntime(config=config)
        events = await _collect_events(rt)

        assert events[-1].type == "final"
        agent_kwargs = runner_calls[0]["starting_agent"].kwargs
        assert "model_settings" not in agent_kwargs
