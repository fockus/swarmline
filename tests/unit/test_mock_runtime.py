"""Stage 16 — verify swarmline.testing.MockRuntime contract."""

from __future__ import annotations

from swarmline import Agent, AgentConfig
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.types import Message
from swarmline.testing import MockRuntime


async def _collect(rt: MockRuntime, messages: list[Message]) -> tuple[str, list]:
    events = []
    async for event in rt.run(messages=messages, system_prompt="", active_tools=[]):
        events.append(event)
    final = events[-1]
    return final.text, events


async def test_mock_runtime_default_reply_for_capital_of_france() -> None:
    rt = MockRuntime()
    text, _ = await _collect(
        rt, [Message(role="user", content="What is the capital of France?")]
    )
    assert "Paris" in text


async def test_mock_runtime_streams_assistant_deltas_then_final() -> None:
    rt = MockRuntime()
    text, events = await _collect(
        rt, [Message(role="user", content="What is 17 * 23?")]
    )
    assert "391" in text
    delta_events = [e for e in events if e.type == "assistant_delta"]
    assert len(delta_events) >= 1
    assert events[-1].type == "final"


async def test_mock_runtime_default_session_id_can_be_overridden() -> None:
    rt = MockRuntime(session_id="my-test-session")
    _, events = await _collect(rt, [Message(role="user", content="hi")])
    # session_id lives in event.data for the final event
    assert events[-1].data.get("session_id") == "my-test-session"


async def test_mock_runtime_remembers_name_in_conversation() -> None:
    """name_memory=True (default) lets the runtime "remember" across messages."""
    rt = MockRuntime()
    history = [
        Message(role="user", content="My name is Alice"),
        Message(role="assistant", content="Nice to meet you, Alice."),
        Message(role="user", content="What's my name?"),
    ]
    text, _ = await _collect(rt, history)
    assert "Alice" in text


async def test_mock_runtime_custom_replies_take_precedence() -> None:
    rt = MockRuntime(replies={"weather": "Sunny and 25°C."})
    text, _ = await _collect(rt, [Message(role="user", content="How is the weather?")])
    assert "Sunny" in text


async def test_mock_runtime_fallback_for_unmatched_input() -> None:
    rt = MockRuntime(name_memory=False)  # disable memory pattern
    text, _ = await _collect(rt, [Message(role="user", content="Anything else?")])
    assert text == "You said: Anything else?"


def test_register_default_is_idempotent() -> None:
    MockRuntime.register_default()
    MockRuntime.register_default()  # second call must not raise
    assert get_default_registry().is_registered(MockRuntime.NAME)


async def test_agent_with_mock_runtime_end_to_end() -> None:
    """The whole point: AgentConfig(runtime='mock') works without any API key."""
    MockRuntime.register_default()
    agent = Agent(
        AgentConfig(
            system_prompt="You are a helpful assistant.",
            runtime=MockRuntime.NAME,
        )
    )
    result = await agent.query("What is the capital of France?")
    assert "Paris" in result.text


def test_mock_runtime_name_constant() -> None:
    assert MockRuntime.NAME == "mock"


async def test_mock_runtime_cancel_and_cleanup_are_noops() -> None:
    rt = MockRuntime()
    rt.cancel()  # must not raise
    await rt.cleanup()  # must not raise
