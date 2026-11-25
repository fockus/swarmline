"""Unit: Agent.stream(prompt, messages=...) — conversation history in streaming path.

MAJOR 3 fix: Agent.stream() previously accepted only `prompt` and silently dropped any
conversation history.  This test verifies that the `messages` parameter is threaded from
stream() → _stream_with_config() → _execute_stream(), mirroring the behaviour of
Agent.query(prompt, messages=...).

Backward-compatible: stream(prompt) with no messages works identically to before.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort
from swarmline.domain_types import Message

try:
    from conftest import FakeStreamEvent
except ImportError:
    # Fallback minimal fake for isolated runs
    class FakeStreamEvent:  # type: ignore[no-redef]
        def __init__(self, type: str, text: str = "", is_final: bool = False) -> None:
            self.type = type
            self.text = text
            self.is_final = is_final


def _make_agent(**overrides: Any) -> Agent:
    cfg = AgentConfig(system_prompt="test", **overrides)
    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    return Agent(cfg, runtime_factory=factory)


class TestAgentStreamMessagesParam:
    """Agent.stream() threads messages to _execute_stream — MAJOR 3."""

    @pytest.mark.asyncio
    async def test_stream_with_messages_forwards_to_execute_stream(self) -> None:
        """stream(prompt, messages=[...]) forwards messages kwarg to _execute_stream."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_execute_stream(prompt: str, config: Any = None, **kwargs: Any):  # noqa: ARG001
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        history = [
            Message(role="user", content="previous question"),
            Message(role="assistant", content="previous answer"),
        ]
        with patch.object(agent, "_execute_stream", side_effect=fake_execute_stream):
            async for _ in agent.stream("current prompt", messages=history):
                pass

        assert "messages" in received_kwargs, (
            "stream() must forward messages to _execute_stream"
        )
        assert received_kwargs["messages"] == history

    @pytest.mark.asyncio
    async def test_stream_without_messages_passes_none(self) -> None:
        """stream(prompt) with no messages passes messages=None (backward-compatible)."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_execute_stream(prompt: str, config: Any = None, **kwargs: Any):  # noqa: ARG001
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_execute_stream):
            async for _ in agent.stream("hello"):
                pass

        # messages kwarg not set (None by default — no history)
        assert received_kwargs.get("messages") is None

    @pytest.mark.asyncio
    async def test_stream_with_empty_messages_list_passes_none_or_empty(self) -> None:
        """stream(prompt, messages=[]) is backward-compatible (empty = no history)."""
        agent = _make_agent()
        received_kwargs: dict[str, Any] = {}

        async def fake_execute_stream(prompt: str, config: Any = None, **kwargs: Any):  # noqa: ARG001
            received_kwargs.update(kwargs)
            yield FakeStreamEvent("done", text="ok", is_final=True)

        with patch.object(agent, "_execute_stream", side_effect=fake_execute_stream):
            async for _ in agent.stream("hello", messages=[]):
                pass

        # An empty list must not be treated as non-empty history.
        msgs = received_kwargs.get("messages")
        assert not msgs  # None or []
