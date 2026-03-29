"""Unit: CognitiaA2AAdapter — wraps Agent as A2A service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


from cognitia.a2a.adapter import CognitiaA2AAdapter, _extract_user_text
from cognitia.a2a.types import (
    AgentSkill,
    Message,
    Task,
    TaskState,
    TextPart,
)
from cognitia.agent.result import Result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(text: str = "Agent response", ok: bool = True) -> MagicMock:
    agent = MagicMock()
    agent.query = AsyncMock(
        return_value=Result(text=text, error=None if ok else "error")
    )
    return agent


def _task_with_message(text: str, task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        messages=[Message(role="user", parts=[TextPart(text=text)])],
    )


# ---------------------------------------------------------------------------
# AgentCard generation
# ---------------------------------------------------------------------------


class TestAdapterAgentCard:

    def test_agent_card_has_name_and_url(self) -> None:
        adapter = CognitiaA2AAdapter(
            _mock_agent(), name="TestBot", url="http://localhost:9000"
        )
        card = adapter.agent_card
        assert card.name == "TestBot"
        assert card.url == "http://localhost:9000"

    def test_agent_card_has_streaming_capability(self) -> None:
        adapter = CognitiaA2AAdapter(_mock_agent())
        assert adapter.agent_card.capabilities.streaming is True

    def test_agent_card_with_skills(self) -> None:
        skills = [AgentSkill(id="search", name="Search")]
        adapter = CognitiaA2AAdapter(_mock_agent(), skills=skills)
        assert len(adapter.agent_card.skills) == 1
        assert adapter.agent_card.skills[0].id == "search"


# ---------------------------------------------------------------------------
# handle_task (non-streaming)
# ---------------------------------------------------------------------------


class TestAdapterHandleTask:

    async def test_handle_task_success(self) -> None:
        agent = _mock_agent(text="Hello from agent")
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi")

        result = await adapter.handle_task(task)

        assert result.status.state == TaskState.COMPLETED
        assert len(result.messages) == 2  # user + agent
        assert result.messages[1].role == "agent"

    async def test_handle_task_calls_agent_query(self) -> None:
        agent = _mock_agent()
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Test prompt")

        await adapter.handle_task(task)

        agent.query.assert_called_once_with("Test prompt")

    async def test_handle_task_no_user_message_fails(self) -> None:
        agent = _mock_agent()
        adapter = CognitiaA2AAdapter(agent)
        task = Task(id="t1", messages=[])

        result = await adapter.handle_task(task)

        assert result.status.state == TaskState.FAILED

    async def test_handle_task_agent_error_sets_failed(self) -> None:
        agent = _mock_agent(ok=False)
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi")

        result = await adapter.handle_task(task)

        assert result.status.state == TaskState.FAILED

    async def test_handle_task_exception_sets_failed(self) -> None:
        agent = MagicMock()
        agent.query = AsyncMock(side_effect=RuntimeError("boom"))
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi")

        result = await adapter.handle_task(task)

        assert result.status.state == TaskState.FAILED


# ---------------------------------------------------------------------------
# handle_task_streaming
# ---------------------------------------------------------------------------


class TestAdapterHandleTaskStreaming:

    async def test_streaming_emits_working_then_completed(self) -> None:
        agent = MagicMock()

        async def fake_stream(prompt: str) -> Any:
            class E:
                def __init__(self, **kw: Any) -> None:
                    self.__dict__.update(kw)
            yield E(type="text_delta", text="Hello ")
            yield E(type="done", text="Hello World", is_final=True)

        agent.stream = fake_stream
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi")

        events = []
        async for event in adapter.handle_task_streaming(task):
            events.append(event)

        assert len(events) == 2
        assert events[0].status.state == TaskState.WORKING
        assert events[0].final is False
        assert events[1].status.state == TaskState.COMPLETED
        assert events[1].final is True


# ---------------------------------------------------------------------------
# get_task / cancel_task
# ---------------------------------------------------------------------------


class TestAdapterTaskManagement:

    async def test_get_task_after_handle(self) -> None:
        agent = _mock_agent()
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi", task_id="lookup-1")

        await adapter.handle_task(task)

        found = adapter.get_task("lookup-1")
        assert found is not None
        assert found.id == "lookup-1"

    async def test_get_task_not_found(self) -> None:
        adapter = CognitiaA2AAdapter(_mock_agent())
        assert adapter.get_task("nonexistent") is None

    async def test_cancel_task(self) -> None:
        agent = _mock_agent()
        adapter = CognitiaA2AAdapter(agent)
        task = _task_with_message("Hi", task_id="cancel-1")
        await adapter.handle_task(task)

        # Task is already completed, cancel should not change state
        canceled = await adapter.cancel_task("cancel-1")
        assert canceled is not None
        assert canceled.status.state == TaskState.COMPLETED

    async def test_cancel_nonexistent_task(self) -> None:
        adapter = CognitiaA2AAdapter(_mock_agent())
        result = await adapter.cancel_task("nope")
        assert result is None


# ---------------------------------------------------------------------------
# _extract_user_text
# ---------------------------------------------------------------------------


class TestExtractUserText:

    def test_extracts_text_from_user_message(self) -> None:
        task = _task_with_message("Hello world")
        assert _extract_user_text(task) == "Hello world"

    def test_returns_empty_for_no_messages(self) -> None:
        task = Task(messages=[])
        assert _extract_user_text(task) == ""

    def test_returns_last_user_message(self) -> None:
        task = Task(messages=[
            Message(role="user", parts=[TextPart(text="First")]),
            Message(role="agent", parts=[TextPart(text="Reply")]),
            Message(role="user", parts=[TextPart(text="Second")]),
        ])
        assert _extract_user_text(task) == "Second"
