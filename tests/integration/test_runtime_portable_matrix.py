"""Integration: portable matrix for full runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
from swarmline.agent import Agent, AgentConfig
from swarmline.runtime.adapter import StreamEvent
from swarmline.runtime.types import Message, RuntimeEvent

pytestmark = pytest.mark.integration


def _portable_reply(prompt: str) -> str:
    return f"portable:{prompt}"


def _make_done_event(
    prompt: str,
    runtime_name: str,
    new_messages: list[Message] | None = None,
) -> StreamEvent:
    event = StreamEvent(
        type="done",
        text=_portable_reply(prompt),
        is_final=True,
    )
    event.native_metadata = {
        "runtime_name": runtime_name,
        "feature_mode": "portable",
    }
    if new_messages is not None:
        event.new_messages = [message.to_dict() for message in new_messages]
    return event


class FakePortableRuntime:
    def __init__(self, include_new_messages: bool = False) -> None:
        self._include_new_messages = include_new_messages

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[Any],
        config: Any | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        prompt = messages[-1].content
        yield RuntimeEvent.assistant_delta("portable:")
        yield RuntimeEvent.assistant_delta(prompt)
        new_messages = None
        if self._include_new_messages:
            new_messages = [
                Message(role="assistant", content="portable:"),
                Message(role="assistant", content=prompt),
                Message(role="assistant", content=_portable_reply(prompt)),
            ]
        yield RuntimeEvent.final(
            text=_portable_reply(prompt),
            new_messages=new_messages,
            native_metadata={
                "runtime_name": "deepagents",
                "feature_mode": "portable",
            },
        )

    async def cleanup(self) -> None:
        return None


class FakePortableAdapter:
    def __init__(self, include_new_messages: bool = False) -> None:
        self._include_new_messages = include_new_messages

    async def stream_reply(self, prompt: str) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="portable:")
        yield StreamEvent(type="text_delta", text=prompt)
        new_messages = None
        if self._include_new_messages:
            new_messages = [
                Message(role="assistant", content="portable:"),
                Message(role="assistant", content=prompt),
                Message(role="assistant", content=_portable_reply(prompt)),
            ]
        yield _make_done_event(prompt, "claude_sdk", new_messages=new_messages)

    async def disconnect(self) -> None:
        return None


@contextmanager
def _patch_runtime_boundary(
    runtime_name: str, include_new_messages: bool = False
) -> Iterator[None]:
    if runtime_name == "deepagents":
        fake_factory = MagicMock()
        fake_factory.create.return_value = FakePortableRuntime(include_new_messages)
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            yield
        return

    async def fake_stream_one_shot_query(
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="portable:")
        yield StreamEvent(type="text_delta", text=prompt)
        yield _make_done_event(prompt, "claude_sdk")

    async def fake_create_adapter(self: Any) -> FakePortableAdapter:
        return FakePortableAdapter(include_new_messages)

    with (
        patch(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            side_effect=fake_stream_one_shot_query,
        ),
        patch(
            "swarmline.agent.conversation.Conversation._create_adapter",
            new=fake_create_adapter,
        ),
    ):
        yield


@pytest.mark.integration
class TestRuntimePortableMatrix:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("runtime_name", ["claude_sdk", "deepagents"])
    async def test_runtime_portable_matrix_query_claude_vs_deepagents(
        self, runtime_name: str
    ) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime=runtime_name,
                feature_mode="portable",
            )
        )

        with _patch_runtime_boundary(runtime_name):
            result = await agent.query("hello")

        assert result.ok is True
        assert result.text == "portable:hello"
        assert result.native_metadata == {
            "runtime_name": runtime_name,
            "feature_mode": "portable",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("runtime_name", ["claude_sdk", "deepagents"])
    async def test_runtime_portable_matrix_stream_claude_vs_deepagents(
        self, runtime_name: str
    ) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime=runtime_name,
                feature_mode="portable",
            )
        )

        with _patch_runtime_boundary(runtime_name):
            events = [event async for event in agent.stream("hello")]

        assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
        assert "".join(event.text for event in events[:-1]) == "portable:hello"
        assert events[-1].text == "portable:hello"
        assert events[-1].native_metadata == {
            "runtime_name": runtime_name,
            "feature_mode": "portable",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("runtime_name", ["claude_sdk", "deepagents"])
    async def test_runtime_portable_matrix_conversation_claude_vs_deepagents(
        self, runtime_name: str
    ) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime=runtime_name,
                feature_mode="portable",
            )
        )

        with _patch_runtime_boundary(runtime_name):
            async with agent.conversation(session_id="matrix-session") as conv:
                first = await conv.say("hello")
                second = await conv.say("again")

        assert first.text == "portable:hello"
        assert second.text == "portable:again"
        assert first.session_id == "matrix-session"
        assert second.session_id == "matrix-session"
        assert len(conv.history) == 4

    @pytest.mark.asyncio
    @pytest.mark.parametrize("runtime_name", ["claude_sdk", "deepagents"])
    async def test_runtime_portable_matrix_conversation_preserves_new_messages(
        self, runtime_name: str
    ) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime=runtime_name,
                feature_mode="portable",
            )
        )

        with _patch_runtime_boundary(runtime_name, include_new_messages=True):
            async with agent.conversation(session_id="matrix-session") as conv:
                result = await conv.say("hello")

        assert result.ok is True
        assert getattr(result, "new_messages", None) == [
            {"role": "assistant", "content": "portable:"},
            {"role": "assistant", "content": "hello"},
            {"role": "assistant", "content": "portable:hello"},
        ]
        assert [msg.role for msg in conv.history] == [
            "user",
            "assistant",
            "assistant",
            "assistant",
        ]


@pytest.mark.integration
class TestDocsSmoke:
    @pytest.mark.asyncio
    async def test_readme_deepagents_quickstart_smoke(self) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="You are a helpful assistant.",
                runtime="deepagents",
                feature_mode="portable",
            )
        )

        with _patch_runtime_boundary("deepagents"):
            result = await agent.query("What is 2+2?")

        assert result.ok is True
        assert result.text == "portable:What is 2+2?"
        assert result.native_metadata == {
            "runtime_name": "deepagents",
            "feature_mode": "portable",
        }
