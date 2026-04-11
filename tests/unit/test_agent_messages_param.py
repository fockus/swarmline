"""Unit: Agent.query() / _execute_stream() / _execute_agent_runtime() — messages parameter.

Contract tests for conversation history support:
- messages parameter accepted and forwarded
- History prepended before current user message
- Backward compatible: messages=None works identically
- Empty messages list = same as None
- Original messages list not mutated
- History order preserved
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort
from swarmline.domain_types import Message
from conftest import FakeStreamEvent


def _make_config(**overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = {"system_prompt": "test prompt"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_agent(config: AgentConfig | None = None, **overrides: Any) -> Agent:
    """Create Agent with a mock RuntimeFactoryPort (no real runtime)."""
    cfg = config or _make_config(**overrides)
    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    return Agent(cfg, runtime_factory=factory)


# ---------------------------------------------------------------------------
# 1. Agent.query() — accepts and forwards messages
# ---------------------------------------------------------------------------


class TestAgentQueryMessagesParam:
    """Agent.query() accepts optional messages parameter."""

    @pytest.mark.asyncio
    async def test_query_with_messages_forwards_to_stream(self) -> None:
        """query(prompt, messages=[...]) forwards messages to _execute_stream."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_stream(prompt: str, config: Any = None, **kwargs: Any):
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            history = [
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi there"),
            ]
            result = await agent.query("follow up", messages=history)

        assert result.ok is True
        assert received_kwargs.get("messages") == [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ]

    @pytest.mark.asyncio
    async def test_query_without_messages_backward_compatible(self) -> None:
        """query(prompt) without messages works identically to before."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_stream(prompt: str, config: Any = None, **kwargs: Any):
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("standalone")

        assert result.ok is True
        assert received_kwargs.get("messages") is None

    @pytest.mark.asyncio
    async def test_query_with_empty_messages_passes_through(self) -> None:
        """query(prompt, messages=[]) passes empty list through."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_stream(prompt: str, config: Any = None, **kwargs: Any):
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("standalone", messages=[])

        assert result.ok is True
        # Empty list passed through as-is
        assert received_kwargs.get("messages") is not None


# ---------------------------------------------------------------------------
# 2. _execute_stream() — routes messages to the right runtime handler
# ---------------------------------------------------------------------------


class TestExecuteStreamMessagesParam:
    """_execute_stream() forwards messages through dispatch_runtime."""

    @pytest.mark.asyncio
    async def test_stream_forwards_messages_to_agent_runtime(self) -> None:
        """_execute_stream(prompt, messages=[...]) routes to _execute_agent_runtime with messages."""
        agent = _make_agent(runtime="thin")
        received: dict[str, Any] = {}

        async def fake_agent_runtime(
            prompt: str, runtime_name: str, config: Any = None, **kwargs: Any,
        ):
            received["prompt"] = prompt
            received["runtime_name"] = runtime_name
            received["messages"] = kwargs.get("messages")
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_agent_runtime", side_effect=fake_agent_runtime):
            events = []
            history = [Message(role="user", content="prev")]
            async for event in agent._execute_stream("next", messages=history):
                events.append(event)

        assert received["messages"] == [Message(role="user", content="prev")]

    @pytest.mark.asyncio
    async def test_stream_forwards_messages_to_claude_sdk(self) -> None:
        """_execute_stream(prompt, messages=[...]) routes to _execute_claude_sdk with messages."""
        agent = _make_agent(runtime="claude_sdk")
        received: dict[str, Any] = {}

        async def fake_claude_sdk(
            prompt: str, config: Any = None, **kwargs: Any,
        ):
            received["prompt"] = prompt
            received["messages"] = kwargs.get("messages")
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_claude_sdk", side_effect=fake_claude_sdk):
            events = []
            history = [Message(role="user", content="prev")]
            async for event in agent._execute_stream("next", messages=history):
                events.append(event)

        assert received["messages"] == [Message(role="user", content="prev")]

    @pytest.mark.asyncio
    async def test_stream_without_messages_backward_compatible(self) -> None:
        """_execute_stream(prompt) without messages works identically."""
        agent = _make_agent(runtime="thin")
        received: dict[str, Any] = {}

        async def fake_agent_runtime(
            prompt: str, runtime_name: str, config: Any = None, **kwargs: Any,
        ):
            received["messages"] = kwargs.get("messages")
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_agent_runtime", side_effect=fake_agent_runtime):
            async for _ in agent._execute_stream("hello"):
                pass

        assert received["messages"] is None


# ---------------------------------------------------------------------------
# 3. _execute_agent_runtime() — builds message list for portable runtimes
# ---------------------------------------------------------------------------


class TestAgentRuntimeMessagesParam:
    """_execute_agent_runtime() prepends history messages before current user message."""

    @pytest.mark.asyncio
    async def test_messages_prepended_before_current_prompt(self) -> None:
        """History messages appear before the current user message in the API call."""
        agent = _make_agent(runtime="thin")
        captured_messages: list[Message] = []

        original_run_portable = None

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            captured_messages.extend(messages)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            history = [
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi there"),
            ]
            async for _ in agent._execute_agent_runtime(
                "follow up", "thin", messages=history,
            ):
                pass

        assert len(captured_messages) == 3
        assert captured_messages[0].role == "user"
        assert captured_messages[0].content == "hello"
        assert captured_messages[1].role == "assistant"
        assert captured_messages[1].content == "hi there"
        assert captured_messages[2].role == "user"
        assert captured_messages[2].content == "follow up"

    @pytest.mark.asyncio
    async def test_no_messages_single_user_message(self) -> None:
        """Without messages param, only current user message is sent."""
        agent = _make_agent(runtime="thin")
        captured_messages: list[Message] = []

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            captured_messages.extend(messages)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            async for _ in agent._execute_agent_runtime("hello", "thin"):
                pass

        assert len(captured_messages) == 1
        assert captured_messages[0].role == "user"
        assert captured_messages[0].content == "hello"

    @pytest.mark.asyncio
    async def test_empty_messages_list_single_user_message(self) -> None:
        """Empty messages list results in only current user message."""
        agent = _make_agent(runtime="thin")
        captured_messages: list[Message] = []

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            captured_messages.extend(messages)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            async for _ in agent._execute_agent_runtime(
                "hello", "thin", messages=[],
            ):
                pass

        assert len(captured_messages) == 1
        assert captured_messages[0].content == "hello"

    @pytest.mark.asyncio
    async def test_messages_none_single_user_message(self) -> None:
        """messages=None results in only current user message."""
        agent = _make_agent(runtime="thin")
        captured_messages: list[Message] = []

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            captured_messages.extend(messages)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            async for _ in agent._execute_agent_runtime(
                "hello", "thin", messages=None,
            ):
                pass

        assert len(captured_messages) == 1
        assert captured_messages[0].content == "hello"

    @pytest.mark.asyncio
    async def test_history_order_preserved(self) -> None:
        """Multiple history messages maintain their original order."""
        agent = _make_agent(runtime="thin")
        captured_messages: list[Message] = []

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            captured_messages.extend(messages)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            history = [
                Message(role="user", content="msg1"),
                Message(role="assistant", content="msg2"),
                Message(role="user", content="msg3"),
                Message(role="assistant", content="msg4"),
            ]
            async for _ in agent._execute_agent_runtime(
                "msg5", "thin", messages=history,
            ):
                pass

        assert len(captured_messages) == 5
        assert [m.content for m in captured_messages] == [
            "msg1", "msg2", "msg3", "msg4", "msg5",
        ]
        assert captured_messages[-1].role == "user"

    @pytest.mark.asyncio
    async def test_original_messages_list_not_mutated(self) -> None:
        """The caller's messages list must not be modified in-place."""
        agent = _make_agent(runtime="thin")

        async def fake_run_portable(
            agent_config: Any,
            runtime_name: str,
            *,
            messages: list[Any],
            system_prompt: str,
            **kwargs: Any,
        ):
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.run_portable_runtime",
            side_effect=fake_run_portable,
        ):
            history = [Message(role="user", content="hello")]
            original_len = len(history)
            async for _ in agent._execute_agent_runtime(
                "world", "thin", messages=history,
            ):
                pass

        assert len(history) == original_len, "Original messages list was mutated"


# ---------------------------------------------------------------------------
# 4. _execute_claude_sdk() — history injected into prompt text
# ---------------------------------------------------------------------------


class TestClaudeSdkMessagesParam:
    """_execute_claude_sdk() injects history into prompt for Claude SDK."""

    @pytest.mark.asyncio
    async def test_claude_sdk_prepends_history_to_prompt(self) -> None:
        """Messages are formatted as conversation history text for Claude SDK."""
        agent = _make_agent(runtime="claude_sdk")
        captured_prompt: list[str] = []

        async def fake_stream_one_shot(prompt: str, config: Any, **kwargs: Any):
            captured_prompt.append(prompt)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.stream_claude_one_shot",
            side_effect=fake_stream_one_shot,
        ):
            history = [
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi there"),
            ]
            async for _ in agent._execute_claude_sdk(
                "follow up", messages=history,
            ):
                pass

        assert len(captured_prompt) == 1
        assert "[Conversation history]" in captured_prompt[0]
        assert "[user]: hello" in captured_prompt[0]
        assert "[assistant]: hi there" in captured_prompt[0]
        assert "[Current message]" in captured_prompt[0]
        assert "follow up" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_claude_sdk_no_messages_passes_prompt_as_is(self) -> None:
        """Without messages, prompt is passed unmodified to stream_one_shot."""
        agent = _make_agent(runtime="claude_sdk")
        captured_prompt: list[str] = []

        async def fake_stream_one_shot(prompt: str, config: Any, **kwargs: Any):
            captured_prompt.append(prompt)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch(
            "swarmline.agent.agent.stream_claude_one_shot",
            side_effect=fake_stream_one_shot,
        ):
            async for _ in agent._execute_claude_sdk("standalone"):
                pass

        assert len(captured_prompt) == 1
        assert captured_prompt[0] == "standalone"
