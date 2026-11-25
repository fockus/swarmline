"""Unit: ``Agent.query/stream(prompt, prompt_blocks=...)`` — images in the CURRENT user turn.

Contract (taskloom Sprint 7i S1, AGR-088):
- without ``prompt_blocks`` the messages handed to the runtime are exactly what they were;
- with blocks, ONLY the last (current) user message carries
  ``content_blocks=[TextBlock(prompt), *blocks]``; its ``content`` stays the plain prompt;
- history messages never carry blocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from swarmline.agent import agent as agent_module
from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort
from swarmline.domain_types import ImageBlock, Message, TextBlock
from conftest import FakeStreamEvent

IMAGE = ImageBlock(data="aGVsbG8=", media_type="image/png")


def _agent() -> Agent:
    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    return Agent(
        AgentConfig(system_prompt="sys", runtime="thin"), runtime_factory=factory
    )


class _RuntimeSpy:
    """Stands in for ``run_portable_runtime``: records the messages a runtime would get."""

    def __init__(self) -> None:
        self.messages: list[Message] | None = None

    async def __call__(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.messages = list(kwargs["messages"])
        yield FakeStreamEvent("done", text="ok", is_final=True)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _RuntimeSpy:
    recorder = _RuntimeSpy()
    monkeypatch.setattr(agent_module, "run_portable_runtime", recorder)
    return recorder


async def test_query_without_prompt_blocks_byte_identical(spy: _RuntimeSpy) -> None:
    history = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]

    await _agent().query("describe", messages=history)
    implicit = spy.messages
    await _agent().query("describe", messages=history, prompt_blocks=None)
    explicit_none = spy.messages
    await _agent().query("describe", messages=history, prompt_blocks=[])
    empty = spy.messages

    expected = [*history, Message(role="user", content="describe")]
    assert implicit == expected
    assert explicit_none == expected
    assert empty == expected
    assert [m.to_dict() for m in implicit or []] == [m.to_dict() for m in expected]


async def test_query_prompt_blocks_on_last_user_message_only(spy: _RuntimeSpy) -> None:
    result = await _agent().query("what is on it?", prompt_blocks=[IMAGE])

    assert result.ok is True
    assert spy.messages == [
        Message(
            role="user",
            content="what is on it?",
            content_blocks=[TextBlock(text="what is on it?"), IMAGE],
        )
    ]


async def test_history_messages_never_carry_blocks(spy: _RuntimeSpy) -> None:
    history = [
        Message(role="user", content="earlier"),
        Message(role="assistant", content="answer"),
    ]

    await _agent().query("now this one", messages=history, prompt_blocks=[IMAGE, IMAGE])

    assert spy.messages is not None
    assert [m.content_blocks for m in spy.messages[:-1]] == [None, None]
    assert spy.messages[-1].content_blocks == [
        TextBlock(text="now this one"),
        IMAGE,
        IMAGE,
    ]


async def test_stream_prompt_blocks_reach_the_runtime(spy: _RuntimeSpy) -> None:
    events = [e async for e in _agent().stream("look", prompt_blocks=[IMAGE])]

    assert events and events[-1].type == "done"
    assert spy.messages is not None
    assert spy.messages[-1].content_blocks == [TextBlock(text="look"), IMAGE]


async def test_prompt_blocks_follow_the_middleware_rewritten_prompt(
    spy: _RuntimeSpy,
) -> None:
    class _Upper:
        async def before_query(self, prompt: str, config: Any) -> str:
            del config
            return prompt.upper()

        async def after_result(self, result: Any) -> Any:
            return result

        def get_hooks(self) -> None:
            return None

    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    agent = Agent(
        AgentConfig(system_prompt="sys", runtime="thin", middleware=(_Upper(),)),
        runtime_factory=factory,
    )

    await agent.query("look", prompt_blocks=[IMAGE])

    assert spy.messages is not None
    assert spy.messages[-1].content == "LOOK"
    assert spy.messages[-1].content_blocks == [TextBlock(text="LOOK"), IMAGE]


async def test_claude_sdk_runtime_drops_prompt_blocks_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    received: dict[str, Any] = {}

    async def fake_one_shot(
        prompt: str, config: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        del config, kwargs
        received["prompt"] = prompt
        yield FakeStreamEvent("done", text="ok", is_final=True)

    monkeypatch.setattr(agent_module, "stream_claude_one_shot", fake_one_shot)
    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    agent = Agent(
        AgentConfig(system_prompt="sys", runtime="claude_sdk"), runtime_factory=factory
    )

    with caplog.at_level("WARNING", logger="swarmline.agent.agent"):
        result = await agent.query("look", prompt_blocks=[IMAGE])

    assert result.ok is True
    assert received["prompt"] == "look"
    assert "prompt_blocks" in caplog.text
