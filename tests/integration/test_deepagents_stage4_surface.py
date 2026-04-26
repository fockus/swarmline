"""Integration: Stage 4 surface for DeepAgents runtime."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("langgraph", reason="langgraph не установлен")
from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.conversation import Conversation
from swarmline.runtime.deepagents import DeepAgentsRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent


class FakeRuntime:
    def __init__(self, events: list[RuntimeEvent]) -> None:
        self._events = events

    async def run(self, **kwargs: Any):
        for event in self._events:
            yield event

    async def cleanup(self) -> None:
        return None


@pytest.mark.integration
class TestDeepAgentsStage4Surface:
    @pytest.mark.asyncio
    async def test_agent_query_exposes_native_metadata_in_result(self) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime="deepagents",
            )
        )

        runtime = FakeRuntime(
            [
                RuntimeEvent.native_notice(
                    "DeepAgents native thread semantics active",
                    metadata={"thread_id": "thread-1"},
                ),
                RuntimeEvent.final(
                    "ok",
                    session_id="thread-1",
                    native_metadata={
                        "thread_id": "thread-1",
                        "history_source": "native_thread",
                    },
                ),
            ]
        )
        fake_factory = MagicMock()
        fake_factory.create.return_value = runtime

        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            result = await agent.query("hello")

        assert result.ok is True
        assert result.session_id == "thread-1"
        assert result.native_metadata == {
            "thread_id": "thread-1",
            "history_source": "native_thread",
        }

    @pytest.mark.asyncio
    async def test_conversation_passes_thread_id_into_deepagents_runtime_config(
        self,
    ) -> None:
        agent = Agent(
            AgentConfig(
                system_prompt="Be helpful",
                runtime="deepagents",
                native_config={"checkpointer": object()},
            )
        )
        conv = Conversation(agent=agent, session_id="conv-thread-1")

        runtime = FakeRuntime([RuntimeEvent.final("ok")])
        fake_factory = MagicMock()
        fake_factory.create.return_value = runtime

        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            async for _ in conv._execute_agent_runtime("hello", "deepagents"):
                pass

        config = fake_factory.create.call_args.kwargs["config"]
        assert config.native_config["thread_id"] == "conv-thread-1"


@pytest.mark.integration
class TestDeepAgentsStage4RuntimeRoundtrip:
    @pytest.mark.asyncio
    async def test_hitl_then_resume_roundtrip_on_native_runtime(self) -> None:
        """Offline integration: interrupt -> resume prohodit cherez real runtime.run()."""

        class FakeGraph:
            def __init__(self) -> None:
                self.calls: list[tuple[Any, Any]] = []

            async def astream_events(
                self, payload: Any, config: Any = None, *, version: str
            ):
                self.calls.append((payload, config))
                if getattr(payload, "resume", None) is not None:
                    chunk = MagicMock()
                    chunk.content = "approved"
                    yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}
                    return

                yield {
                    "event": "on_chain_stream",
                    "data": {
                        "chunk": {
                            "__interrupt__": (
                                {
                                    "value": {
                                        "action_requests": [
                                            {
                                                "name": "edit_file",
                                                "args": {"path": "app.py"},
                                                "description": "Review edit",
                                            }
                                        ],
                                        "review_configs": [
                                            {
                                                "action_name": "edit_file",
                                                "allowed_decisions": [
                                                    "approve",
                                                    "reject",
                                                ],
                                            }
                                        ],
                                    },
                                    "id": "interrupt-1",
                                },
                            )
                        }
                    },
                }

        fake_graph = FakeGraph()
        base_native_config = {
            "checkpointer": object(),
            "thread_id": "thread-1",
            "interrupt_on": {"edit_file": True},
        }
        runtime = DeepAgentsRuntime(
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                native_config=base_native_config,
            )
        )

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch(
                "swarmline.runtime.deepagents.build_deepagents_graph",
                return_value=fake_graph,
            ),
        ):
            first_events = []
            async for event in runtime.run(
                messages=[Message(role="user", content="edit app.py")],
                system_prompt="sys",
                active_tools=[],
            ):
                first_events.append(event)

        assert [event.type for event in first_events] == [
            "native_notice",
            "approval_required",
            "final",
        ]
        assert first_events[1].data["action_name"] == "edit_file"
        assert first_events[-1].data["session_id"] == "thread-1"
        assert (
            first_events[-1].data["native_metadata"]["history_source"]
            == "native_thread"
        )

        resumed_runtime = DeepAgentsRuntime(
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                native_config={
                    **base_native_config,
                    "resume": {"interrupt-1": {"type": "approve"}},
                },
            )
        )

        with (
            patch(
                "swarmline.runtime.deepagents._check_langchain_available",
                return_value=None,
            ),
            patch(
                "swarmline.runtime.deepagents.build_deepagents_graph",
                return_value=fake_graph,
            ),
        ):
            resumed_events = []
            async for event in resumed_runtime.run(
                messages=[Message(role="user", content="ignored on resume")],
                system_prompt="sys",
                active_tools=[],
            ):
                resumed_events.append(event)

        assert [event.type for event in resumed_events] == [
            "native_notice",
            "assistant_delta",
            "final",
        ]
        assert resumed_events[1].data["text"] == "approved"
        assert resumed_events[-1].data["text"] == "approved"
        assert resumed_events[-1].data["native_metadata"]["resume_requested"] is True

        first_payload, first_config = fake_graph.calls[0]
        assert first_config == {"configurable": {"thread_id": "thread-1"}}
        assert first_payload["messages"][0].content == "edit app.py"

        resumed_payload, resumed_config = fake_graph.calls[1]
        assert resumed_config == {"configurable": {"thread_id": "thread-1"}}
        assert resumed_payload.resume == {"interrupt-1": {"type": "approve"}}
