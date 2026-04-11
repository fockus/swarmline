"""Unit: Agent class — query() + stream() + context manager."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import Middleware
from swarmline.agent.result import Result
from swarmline.agent.tool import tool
from swarmline.runtime.thin.runtime import ThinRuntime
from conftest import FakeStreamEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_cli_process(stdout_lines: list[bytes]) -> MagicMock:
    proc = MagicMock()

    async def _stdout_iter():
        for line in stdout_lines:
            yield line

    proc.stdout = _stdout_iter()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Agent.query()
# ---------------------------------------------------------------------------


class TestAgentQueryBasic:
    """Agent.query() - one-shot queries."""

    @pytest.mark.asyncio
    async def test_query_returns_result(self) -> None:
        """query() -> Result with tekstom."""
        agent = Agent(_make_config())

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent("text_delta", text="Hello ")
            yield FakeStreamEvent("text_delta", text="World")
            yield FakeStreamEvent(
                "done",
                text="Hello World",
                is_final=True,
                session_id="s1",
                total_cost_usd=0.01,
                usage={"input_tokens": 10, "output_tokens": 5},
            )

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("Hi")

        assert result.ok is True
        assert result.text == "Hello World"
        assert result.session_id == "s1"
        assert result.total_cost_usd == 0.01

    @pytest.mark.asyncio
    async def test_query_with_structured_output(self) -> None:
        """output_format -> structured_output in Result."""
        config = _make_config(output_format={"type": "json_schema", "schema": {}})
        agent = Agent(config)

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent(
                "done",
                text="",
                is_final=True,
                structured_output={"score": 85},
            )

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("rate this")

        assert result.structured_output == {"score": 85}

    @pytest.mark.asyncio
    async def test_query_preserves_runtime_new_messages(self) -> None:
        """final.new_messages should byt dostupen downstream consumers."""
        from swarmline.runtime.types import Message

        agent = Agent(_make_config())
        expected_new_messages = [
            Message(role="assistant", content="Thinking"),
            Message(role="tool", content="42", name="calc"),
            Message(role="assistant", content="Final answer"),
        ]

        async def fake_stream(prompt, **_kwargs):
            event = FakeStreamEvent(
                "done",
                text="Final answer",
                is_final=True,
                session_id="s1",
            )
            event.new_messages = [message.to_dict() for message in expected_new_messages]
            yield event

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("Hi")

        assert result.ok is True
        assert result.text == "Final answer"
        assert getattr(result, "new_messages", None) == [
            message.to_dict() for message in expected_new_messages
        ]

    @pytest.mark.asyncio
    async def test_query_thin_output_format_returns_structured_output(self) -> None:
        """runtime=thin not should teryat output_format facade-konfiga."""
        config = _make_config(
            runtime="thin",
            output_format={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name", "age"],
            },
        )
        agent = Agent(config)

        class FakeLLM:
            async def __call__(self, messages: list[dict[str, str]], system_prompt: str) -> str:
                _ = (messages, system_prompt)
                return json.dumps(
                    {
                        "type": "final",
                        "final_message": json.dumps({"name": "John", "age": 30}),
                    }
                )

        fake_factory = MagicMock()
        fake_factory.create.side_effect = lambda **kwargs: ThinRuntime(
            config=kwargs["config"],
            llm_call=FakeLLM(),
        )

        with patch("swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory):
            result = await agent.query("John is 30 years old")

        assert result.ok is True
        assert result.structured_output == {"name": "John", "age": 30}

    @pytest.mark.asyncio
    async def test_query_error_returns_result_not_ok(self) -> None:
        """Runtime error → Result(ok=False, error=...)."""
        agent = Agent(_make_config())

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent("error", text="SDK crashed")

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("Hi")

        assert result.ok is False
        assert "SDK crashed" in (result.error or "")


class TestAgentQueryWithMiddleware:
    """Agent.query() with middleware chain."""

    @pytest.mark.asyncio
    async def test_middleware_before_query_applied(self) -> None:
        """before_query modifitsiruet prompt."""
        call_log: list[str] = []

        class PrefixMiddleware(Middleware):
            async def before_query(self, prompt: str, config: AgentConfig) -> str:
                call_log.append("before")
                return f"[PREFIX] {prompt}"

        config = _make_config(middleware=(PrefixMiddleware(),))
        agent = Agent(config)

        received_prompts: list[str] = []

        async def fake_stream(prompt, **_kwargs):
            received_prompts.append(prompt)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            await agent.query("hello")

        assert received_prompts == ["[PREFIX] hello"]
        assert call_log == ["before"]

    @pytest.mark.asyncio
    async def test_middleware_after_result_applied(self) -> None:
        """after_result obogashchaet Result."""

        class TagMiddleware(Middleware):
            async def after_result(self, result: Result) -> Result:
                from dataclasses import replace

                return replace(result, text=result.text + " [tagged]")

        config = _make_config(middleware=(TagMiddleware(),))
        agent = Agent(config)

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent("done", text="answer", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("q")

        assert result.text == "answer [tagged]"


class TestAgentQueryWithTools:
    """Agent.query() with @tool."""

    @pytest.mark.asyncio
    async def test_tools_from_config_available(self) -> None:
        """Tools from config available pri vypolnotnii."""

        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        config = _make_config(tools=(calc.__tool_definition__,))
        agent = Agent(config)
        assert len(agent.config.tools) == 1
        assert agent.config.tools[0].name == "calc"


class TestAgentRuntimeCapabilities:
    """Agent exposes runtime capability descriptor."""

    def test_runtime_capabilities_for_default_claude(self) -> None:
        agent = Agent(_make_config())
        caps = agent.runtime_capabilities

        assert caps.runtime_name == "claude_sdk"
        assert caps.tier == "full"

    def test_runtime_capabilities_for_thin(self) -> None:
        agent = Agent(_make_config(runtime="thin"))
        caps = agent.runtime_capabilities

        assert caps.runtime_name == "thin"
        assert caps.tier == "light"

    def test_runtime_capabilities_for_custom_runtime(self) -> None:
        from swarmline.runtime.capabilities import RuntimeCapabilities
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        caps = RuntimeCapabilities(
            runtime_name="custom_caps_rt",
            tier="light",
            supports_provider_override=True,
        )
        registry.register("custom_caps_rt", lambda config, **kwargs: object(), capabilities=caps)
        try:
            agent = Agent(_make_config(runtime="custom_caps_rt"))
            resolved = agent.runtime_capabilities
            assert resolved.runtime_name == "custom_caps_rt"
            assert resolved.supports_provider_override is True
        finally:
            registry.unregister("custom_caps_rt")


class TestAgentClaudeSdkWiring:
    """Claude one-shot path probrasyvaet native SDK options."""

    @pytest.mark.asyncio
    async def test_execute_claude_sdk_passes_hooks_and_native_options(self) -> None:
        pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
        from swarmline.hooks.registry import HookRegistry
        from swarmline.skills.types import McpServerSpec

        hooks = HookRegistry()

        async def noop(**kwargs: Any) -> dict[str, Any]:
            return {"continue_": True}

        hooks.on_pre_tool_use(noop)

        config = _make_config(
            hooks=hooks,
            permission_mode="plan",
            max_turns=5,
            max_budget_usd=2.5,
            fallback_model="haiku",
            betas=("context-1m-2025-08-07",),
            env={"MY_VAR": "value"},
            setting_sources=("project",),
            mcp_servers={"iss": McpServerSpec(name="iss", url="http://iss.test")},
            native_config={"include_partial_messages": True},
        )
        agent = Agent(config)
        captured: dict[str, Any] = {}

        async def fake_stream_one_shot_query(prompt: str, **kwargs: Any):
            captured["prompt"] = prompt
            captured.update(kwargs)
            yield FakeStreamEvent("text_delta", text="ok")
            yield FakeStreamEvent("done", text="ok", is_final=True, session_id="s1")

        with patch(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            side_effect=fake_stream_one_shot_query,
        ):
            events = []
            async for event in agent._execute_claude_sdk("hello"):
                events.append(event)

        assert [event.type for event in events] == ["text_delta", "done"]
        assert captured["permission_mode"] == "plan"
        assert captured["max_turns"] == 5
        assert captured["max_budget_usd"] == 2.5
        assert captured["fallback_model"] == "haiku"
        assert captured["betas"] == ["context-1m-2025-08-07"]
        assert captured["env"] == {"MY_VAR": "value"}
        assert captured["setting_sources"] == ["project"]
        assert captured["include_partial_messages"] is True
        assert captured["hooks"] is not None
        assert "iss" in captured["mcp_servers"]

    @pytest.mark.asyncio
    async def test_execute_claude_sdk_true_streaming(self) -> None:
        pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

        agent = Agent(_make_config())

        async def fake_stream_query(prompt: str, **kwargs: Any):
            yield FakeStreamEvent("text_delta", text="Hello ")
            yield FakeStreamEvent("text_delta", text="World")
            yield FakeStreamEvent("done", text="Hello World", is_final=True)

        with patch(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            side_effect=fake_stream_query,
        ):
            events = []
            async for event in agent._execute_claude_sdk("hello"):
                events.append(event)

        assert [event.type for event in events] == ["text_delta", "text_delta", "done"]


class TestAgentRuntimeFactoryWiring:
    """Non-claude runtime path probrasyvaet local tool executors."""

    @pytest.mark.asyncio
    async def test_execute_agent_runtime_passes_tool_executors(self) -> None:
        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        agent = Agent(
            _make_config(
                runtime="deepagents",
                tools=(calc.__tool_definition__,),
            )
        )

        class FakeRuntime:
            async def run(self, **kwargs: Any):
                from swarmline.runtime.types import RuntimeEvent

                yield RuntimeEvent.final("ok")

            async def cleanup(self) -> None:
                return None

        fake_factory = MagicMock()
        fake_factory.create.return_value = FakeRuntime()

        with patch("swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory):
            events = []
            async for event in agent._execute_agent_runtime("hello", "deepagents"):
                events.append(event)

        assert events[-1].type == "done"
        create_kwargs = fake_factory.create.call_args.kwargs
        assert "tool_executors" in create_kwargs
        assert create_kwargs["tool_executors"]["calc"] is calc.__tool_definition__.handler

    @pytest.mark.asyncio
    async def test_execute_agent_runtime_passes_mcp_servers(self) -> None:
        from swarmline.skills.types import McpServerSpec

        agent = Agent(
            _make_config(
                runtime="deepagents",
                mcp_servers={"iss": McpServerSpec(name="iss", url="http://iss.test")},
            )
        )

        class FakeRuntime:
            async def run(self, **kwargs: Any):
                from swarmline.runtime.types import RuntimeEvent

                yield RuntimeEvent.final("ok")

            async def cleanup(self) -> None:
                return None

        fake_factory = MagicMock()
        fake_factory.create.return_value = FakeRuntime()

        with patch("swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory):
            events = []
            async for event in agent._execute_agent_runtime("hello", "deepagents"):
                events.append(event)

        assert events[-1].type == "done"
        create_kwargs = fake_factory.create.call_args.kwargs
        assert create_kwargs["mcp_servers"] == agent.config.mcp_servers

    @pytest.mark.asyncio
    async def test_execute_agent_runtime_omits_mcp_servers_for_cli(self) -> None:
        from swarmline.skills.types import McpServerSpec

        agent = Agent(
            _make_config(
                runtime="cli",
                mcp_servers={"iss": McpServerSpec(name="iss", url="http://iss.test")},
            )
        )

        class FakeRuntime:
            async def run(self, **kwargs: Any):
                from swarmline.runtime.types import RuntimeEvent

                yield RuntimeEvent.final("ok")

            async def cleanup(self) -> None:
                return None

        fake_factory = MagicMock()
        fake_factory.create.return_value = FakeRuntime()

        with patch("swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory):
            events = []
            async for event in agent._execute_agent_runtime("hello", "cli"):
                events.append(event)

        assert events[-1].type == "done"
        create_kwargs = fake_factory.create.call_args.kwargs
        assert "mcp_servers" not in create_kwargs

    @pytest.mark.asyncio
    async def test_execute_agent_runtime_cli_query_works_with_mocked_subprocess(self) -> None:
        agent = Agent(_make_config(runtime="cli"))

        result_line = json.dumps({"type": "result", "result": "cli reply"}).encode() + b"\n"
        mock_process = _make_cli_process([result_line])

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_process)):
            result = await agent.query("hello from cli")

        assert result.ok is True
        assert result.text == "cli reply"
        mock_process.stdin.write.assert_called_once_with(
            b"System instructions:\ntest prompt\n\nConversation:\nuser: hello from cli"
        )

    @pytest.mark.asyncio
    async def test_execute_agent_runtime_cli_query_without_final_returns_error(self) -> None:
        agent = Agent(_make_config(runtime="cli"))
        mock_process = _make_cli_process([b'{"step":"processing"}\n'])

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_process)):
            result = await agent.query("hello from cli")

        assert result.ok is False
        assert "without a final" in (result.error or "")


# ---------------------------------------------------------------------------
# Agent.stream()
# ---------------------------------------------------------------------------


class TestAgentStream:
    """Agent.stream() — streaming events."""

    @pytest.mark.asyncio
    async def test_stream_yields_events(self) -> None:
        agent = Agent(_make_config())

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent("text_delta", text="chunk1")
            yield FakeStreamEvent("text_delta", text="chunk2")
            yield FakeStreamEvent("done", text="chunk1chunk2", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            events = []
            async for event in agent.stream("Hi"):
                events.append(event)

        assert len(events) == 3
        assert events[0].type == "text_delta"
        assert events[1].type == "text_delta"
        assert events[2].type == "done"

    @pytest.mark.asyncio
    async def test_stream_text_deltas(self) -> None:
        agent = Agent(_make_config())
        full = ""

        async def fake_stream(prompt, **_kwargs):
            yield FakeStreamEvent("text_delta", text="Hello ")
            yield FakeStreamEvent("text_delta", text="World")
            yield FakeStreamEvent("done", text="Hello World", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            async for event in agent.stream("Hi"):
                if event.type == "text_delta":
                    full += event.text

        assert full == "Hello World"


# ---------------------------------------------------------------------------
# Agent cleanup + context manager
# ---------------------------------------------------------------------------


class TestAgentLifecycle:
    """Agent cleanup and context manager."""

    @pytest.mark.asyncio
    async def test_cleanup(self) -> None:
        agent = Agent(_make_config())
        # Cleanup on svezhem agente - not should lomatsya
        await agent.cleanup()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """async with Agent → auto cleanup."""
        async with Agent(_make_config()) as agent:
            assert isinstance(agent, Agent)
        # Posle vyhoda - cleanup vyzvan (not lomaetsya)

    @pytest.mark.asyncio
    async def test_conversation_factory(self) -> None:
        """agent.conversation() sozdaet Conversation."""
        agent = Agent(_make_config())
        conv = agent.conversation()
        assert conv is not None
        assert conv._agent is agent


# ---------------------------------------------------------------------------
# _RuntimeEventAdapter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# collect_stream_result / apply_before_query helpers
# ---------------------------------------------------------------------------


class TestCollectStreamResult:
    """collect_stream_result - sbor Result-poley from streama sobytiy."""

    @pytest.mark.asyncio
    async def test_collects_text_deltas(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent("text_delta", text="Hello ")
            yield FakeStreamEvent("text_delta", text="World")
            yield FakeStreamEvent("done", text="", is_final=True)

        result = await collect_stream_result(stream())
        assert result["text"] == "Hello World"

    @pytest.mark.asyncio
    async def test_done_text_overrides_accumulated(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent("text_delta", text="partial")
            yield FakeStreamEvent("done", text="Final answer", is_final=True)

        result = await collect_stream_result(stream())
        assert result["text"] == "Final answer"

    @pytest.mark.asyncio
    async def test_done_empty_text_keeps_accumulated(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent("text_delta", text="accumulated")
            yield FakeStreamEvent("done", text="", is_final=True)

        result = await collect_stream_result(stream())
        assert result["text"] == "accumulated"

    @pytest.mark.asyncio
    async def test_collects_metrics(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent(
                "done",
                text="ok",
                is_final=True,
                session_id="s1",
                total_cost_usd=0.05,
                usage={"input_tokens": 100},
                structured_output={"key": "val"},
                native_metadata={"thread_id": "thread-1"},
            )

        result = await collect_stream_result(stream())
        assert result["session_id"] == "s1"
        assert result["total_cost_usd"] == 0.05
        assert result["usage"] == {"input_tokens": 100}
        assert result["structured_output"] == {"key": "val"}
        assert result["native_metadata"] == {"thread_id": "thread-1"}
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_collects_new_messages(self) -> None:
        from swarmline.agent.agent import collect_stream_result
        from swarmline.runtime.types import Message

        expected_new_messages = [
            Message(role="assistant", content="Thinking"),
            Message(role="tool", content="42", name="calc"),
        ]

        async def stream():
            event = FakeStreamEvent("done", text="Final answer", is_final=True)
            event.new_messages = [message.to_dict() for message in expected_new_messages]
            yield event

        result = await collect_stream_result(stream())
        assert result["new_messages"] == [message.to_dict() for message in expected_new_messages]

    @pytest.mark.asyncio
    async def test_error_event(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent("error", text="boom")

        result = await collect_stream_result(stream())
        assert result["error"] == "boom"
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_error_empty_text_default(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            yield FakeStreamEvent("error", text="")

        result = await collect_stream_result(stream())
        assert result["error"] == "Unknown error"

    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        from swarmline.agent.agent import collect_stream_result

        async def stream():
            return
            yield

        result = await collect_stream_result(stream())
        assert result["text"] == ""
        assert result["error"] is None


class TestApplyBeforeQuery:
    """apply_before_query — middleware chain."""

    @pytest.mark.asyncio
    async def test_empty_middleware(self) -> None:
        from swarmline.agent.agent import apply_before_query

        result = await apply_before_query("hello", (), None)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_single_middleware(self) -> None:
        from swarmline.agent.agent import apply_before_query

        class Prefix(Middleware):
            async def before_query(self, prompt: str, config: Any) -> str:
                return f"[P] {prompt}"

        result = await apply_before_query("hello", (Prefix(),), None)
        assert result == "[P] hello"

    @pytest.mark.asyncio
    async def test_chain_order(self) -> None:
        from swarmline.agent.agent import apply_before_query

        class Add1(Middleware):
            async def before_query(self, prompt: str, config: Any) -> str:
                return prompt + "+1"

        class Add2(Middleware):
            async def before_query(self, prompt: str, config: Any) -> str:
                return prompt + "+2"

        result = await apply_before_query("base", (Add1(), Add2()), None)
        assert result == "base+1+2"


class TestAgentCleanupWithRuntime:
    """Agent.cleanup() with naznachennym runtime."""

    @pytest.mark.asyncio
    async def test_cleanup_calls_runtime_cleanup(self) -> None:
        from unittest.mock import AsyncMock

        agent = Agent(_make_config())
        mock_runtime = AsyncMock()
        mock_runtime.cleanup = AsyncMock()
        agent._runtime = mock_runtime

        await agent.cleanup()

        mock_runtime.cleanup.assert_awaited_once()
        assert agent._runtime is None

    @pytest.mark.asyncio
    async def test_cleanup_runtime_without_cleanup_method(self) -> None:
        """Runtime without metoda cleanup - not lomaetsya."""
        agent = Agent(_make_config())
        agent._runtime = object()

        await agent.cleanup()
        assert agent._runtime is None


# ---------------------------------------------------------------------------
# _RuntimeEventAdapter
# ---------------------------------------------------------------------------


class TestRuntimeEventAdapter:
    """_RuntimeEventAdapter - mapping RuntimeEvent -> StreamEvent-like."""

    def _make_event(self, etype: str, data: dict[str, Any] | None = None) -> Any:
        from swarmline.runtime.types import RuntimeEvent

        return RuntimeEvent(type=etype, data=data or {})

    def test_assistant_delta_maps_to_text_delta(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(self._make_event("assistant_delta", {"text": "Hello"}))
        assert adapted.type == "text_delta"
        assert adapted.text == "Hello"
        assert adapted.is_final is False

    def test_final_maps_to_done(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event(
                "final",
                {
                    "text": "Result",
                    "session_id": "sess-1",
                    "total_cost_usd": 0.5,
                    "usage": {"input_tokens": 10},
                    "structured_output": {"answer": 42},
                    "native_metadata": {"thread_id": "thread-1"},
                    "new_messages": [{"role": "assistant", "content": "Result"}],
                },
            )
        )
        assert adapted.type == "done"
        assert adapted.text == "Result"
        assert adapted.is_final is True
        assert adapted.session_id == "sess-1"
        assert adapted.total_cost_usd == 0.5
        assert adapted.usage == {"input_tokens": 10}
        assert adapted.structured_output == {"answer": 42}
        assert adapted.native_metadata == {"thread_id": "thread-1"}
        assert adapted.new_messages == [{"role": "assistant", "content": "Result"}]

    def test_error_maps_to_error(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(self._make_event("error", {"message": "Something broke"}))
        assert adapted.type == "error"
        assert adapted.text == "Something broke"

    def test_error_default_message(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(self._make_event("error", {}))
        assert adapted.text == "Unknown error"

    def test_tool_call_started(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event("tool_call_started", {"name": "calc", "args": {"x": 1}})
        )
        assert adapted.type == "tool_use_start"
        assert adapted.tool_name == "calc"
        assert adapted.tool_input == {"x": 1}
        assert adapted.text == ""

    def test_tool_call_finished(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event("tool_call_finished", {"name": "calc", "result_summary": "42"})
        )
        assert adapted.type == "tool_use_result"
        assert adapted.tool_name == "calc"
        assert adapted.tool_result == "42"
        assert adapted.text == ""

    def test_unknown_event_passthrough(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(self._make_event("status", {"text": "thinking..."}))
        assert adapted.type == "status"
        assert adapted.text == "thinking..."
        assert adapted.is_final is False

    def test_approval_required_passthrough(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event(
                "approval_required",
                {
                    "action_name": "edit_file",
                    "args": {"path": "app.py"},
                    "allowed_decisions": ["approve", "reject"],
                    "interrupt_id": "interrupt-1",
                    "description": "Review edit",
                },
            )
        )

        assert adapted.type == "approval_required"
        assert adapted.tool_name == "edit_file"
        assert adapted.tool_input == {"path": "app.py"}
        assert adapted.allowed_decisions == ["approve", "reject"]
        assert adapted.interrupt_id == "interrupt-1"
        assert adapted.text == "Review edit"

    def test_user_input_requested_passthrough(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event(
                "user_input_requested",
                {"prompt": "Need answer", "interrupt_id": "interrupt-2"},
            )
        )

        assert adapted.type == "user_input_requested"
        assert adapted.text == "Need answer"
        assert adapted.interrupt_id == "interrupt-2"

    def test_native_notice_passthrough(self) -> None:
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(
            self._make_event(
                "native_notice",
                {"text": "Native thread active", "metadata": {"thread_id": "t1"}},
            )
        )

        assert adapted.type == "native_notice"
        assert adapted.text == "Native thread active"
        assert adapted.native_metadata == {"thread_id": "t1"}

    def test_defaults_always_set(self) -> None:
        """Vse StreamEvent-like atributy vsegda prisutstvuyut."""
        from swarmline.agent.agent import _RuntimeEventAdapter

        adapted = _RuntimeEventAdapter(self._make_event("assistant_delta", {"text": "x"}))
        assert adapted.session_id is None
        assert adapted.total_cost_usd is None
        assert adapted.usage is None
        assert adapted.structured_output is None
        assert adapted.native_metadata is None
        assert adapted.tool_name == ""
        assert adapted.tool_input is None
        assert adapted.tool_result == ""
        assert adapted.allowed_decisions is None
        assert adapted.interrupt_id is None


# ---------------------------------------------------------------------------
# _ErrorEvent
# ---------------------------------------------------------------------------


class TestErrorEvent:
    """_ErrorEvent — simple error event."""

    def test_error_event_attributes(self) -> None:
        from swarmline.agent.agent import _ErrorEvent

        evt = _ErrorEvent("connection lost")
        assert evt.type == "error"
        assert evt.text == "connection lost"
        assert evt.is_final is False
        assert evt.session_id is None
        assert evt.total_cost_usd is None
        assert evt.usage is None
        assert evt.structured_output is None
        assert evt.native_metadata is None
        assert evt.tool_name == ""
        assert evt.tool_input is None
        assert evt.tool_result == ""
        assert evt.allowed_decisions is None
        assert evt.interrupt_id is None
