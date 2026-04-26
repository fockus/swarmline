"""Tests native upstream adapter for DeepAgents."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("deepagents", reason="deepagents не установлен")
from swarmline.runtime.deepagents_native import (
    build_deepagents_graph,
    stream_deepagents_graph_events,
    validate_native_backend_config,
)
from swarmline.runtime.types import ToolSpec


class TestBuildDeepAgentsGraph:
    """Building native upstream graph."""

    def test_build_graph_calls_create_deep_agent(self) -> None:
        """Native builder builds upstream graph with resolved LLM and tools."""
        tools = [ToolSpec(name="search", description="Search", parameters={})]

        with (
            patch(
                "swarmline.runtime.deepagents_native.build_deepagents_chat_model",
                return_value="llm",
            ),
            patch(
                "swarmline.runtime.deepagents_native.create_langchain_tool",
                side_effect=lambda spec, executor: f"tool:{spec.name}",
            ),
            patch("deepagents.create_deep_agent", return_value="graph") as mock_create,
        ):
            graph = build_deepagents_graph(
                model="openai:gpt-4o",
                system_prompt="sys",
                tools=tools,
                tool_executors={},
                base_url="https://proxy.test",
                interrupt_on={"edit_file": True},
                checkpointer="cp",
                store="store",
                backend="sandbox",
            )

        assert graph == "graph"
        mock_create.assert_called_once_with(
            model="llm",
            tools=["tool:search"],
            system_prompt="sys",
            interrupt_on={"edit_file": True},
            checkpointer="cp",
            store="store",
            backend="sandbox",
        )

    def test_build_graph_filters_native_builtins_and_keeps_local_executor(self) -> None:
        """Native builder does not duplicate upstream built-ins and retains local executor."""
        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="execute", description="shell", parameters={}),
            ToolSpec(name="calc", description="Search", parameters={}, is_local=True),
        ]

        async def calc(**kwargs):
            return "42"

        with (
            patch(
                "swarmline.runtime.deepagents_native.build_deepagents_chat_model",
                return_value="llm",
            ),
            patch(
                "swarmline.runtime.deepagents_native.create_langchain_tool",
                side_effect=lambda spec, executor: (spec.name, executor),
            ) as mock_tool,
            patch("deepagents.create_deep_agent", return_value="graph") as mock_create,
        ):
            build_deepagents_graph(
                model="openai:gpt-4o",
                system_prompt="sys",
                tools=tools,
                tool_executors={"calc": calc},
            )

        assert mock_tool.call_count == 1
        assert mock_tool.call_args.args[0].name == "calc"
        assert mock_tool.call_args.args[1] is calc
        mock_create.assert_called_once_with(
            model="llm",
            tools=[("calc", calc)],
            system_prompt="sys",
        )

    def test_validate_native_backend_config_requires_backend_for_native_builtins(
        self,
    ) -> None:
        """Native built-ins without backend should fail-fast."""
        error = validate_native_backend_config(
            native_tool_names=["execute", "read_file"],
            native_config={},
        )

        assert error is not None
        assert error.kind == "capability_unsupported"
        assert "backend" in error.message
        assert error.details == {"native_tools": ["execute", "read_file"]}

    def test_validate_native_backend_config_allows_no_backend_without_native_builtins(
        self,
    ) -> None:
        """If native built-ins are not requested, backend is not required."""
        error = validate_native_backend_config(
            native_tool_names=[],
            native_config={},
        )

        assert error is None


class TestBuildDeepAgentsGraphUpstreamParams:
    """Phase 1: Forwarding upstream parameters memory/subagents/skills/middleware/name."""

    def _build_with_mock(self, **extra_kwargs) -> MagicMock:
        """Helper: call build_deepagents_graph with mocks and return mock_create."""
        with (
            patch(
                "swarmline.runtime.deepagents_native.build_deepagents_chat_model",
                return_value="llm",
            ),
            patch(
                "swarmline.runtime.deepagents_native.create_langchain_tool",
                side_effect=lambda spec, executor: f"tool:{spec.name}",
            ),
            patch("deepagents.create_deep_agent", return_value="graph") as mock_create,
        ):
            build_deepagents_graph(
                model="sonnet",
                system_prompt="sys",
                tools=[],
                tool_executors={},
                **extra_kwargs,
            )
        return mock_create

    def test_memory_passed_to_create_deep_agent(self) -> None:
        mock_create = self._build_with_mock(memory=["./AGENTS.md"])
        assert mock_create.call_args.kwargs["memory"] == ["./AGENTS.md"]

    def test_subagents_passed_to_create_deep_agent(self) -> None:
        sa = [{"name": "r", "description": "d", "system_prompt": "s"}]
        mock_create = self._build_with_mock(subagents=sa)
        assert mock_create.call_args.kwargs["subagents"] == sa

    def test_skills_passed_to_create_deep_agent(self) -> None:
        skills = [{"name": "search", "description": "Search web"}]
        mock_create = self._build_with_mock(skills=skills)
        assert mock_create.call_args.kwargs["skills"] == skills

    def test_middleware_passed_to_create_deep_agent(self) -> None:
        mw = [MagicMock()]
        mock_create = self._build_with_mock(middleware=mw)
        assert mock_create.call_args.kwargs["middleware"] == mw

    def test_agent_name_passed_to_create_deep_agent(self) -> None:
        mock_create = self._build_with_mock(agent_name="my-agent")
        assert mock_create.call_args.kwargs["name"] == "my-agent"

    def test_no_new_params_does_not_add_keys(self) -> None:
        """Without new parameters - kwargs do not contain new keys (regression)."""
        mock_create = self._build_with_mock()
        kwargs = mock_create.call_args.kwargs
        for key in ("memory", "subagents", "skills", "middleware", "name"):
            assert key not in kwargs


class TestStreamDeepAgentsGraphEvents:
    """Normalization of upstream graph events in RuntimeEvent."""

    @pytest.mark.asyncio
    async def test_stream_maps_text_and_tool_events(self) -> None:
        """String chunks and tool events are mapped in RuntimeEvent."""
        chunk = MagicMock()
        chunk.content = "hello"

        graph = MagicMock()

        async def fake_astream_events(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}
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
                                            "allowed_decisions": ["approve", "reject"],
                                        }
                                    ],
                                },
                                "id": "interrupt-1",
                            },
                        )
                    }
                },
            }
            yield {
                "event": "on_tool_start",
                "name": "search",
                "data": {"input": {"q": "hi"}},
                "run_id": "run-1",
            }
            yield {
                "event": "on_tool_end",
                "name": "search",
                "data": {"output": "done"},
                "run_id": "run-1",
            }

        graph.astream_events = fake_astream_events

        events = []
        async for event in stream_deepagents_graph_events(
            graph=graph,
            input_payload={"messages": ["msg"]},
            run_config={"configurable": {"thread_id": "thread-1"}},
        ):
            events.append(event)

        assert [event.type for event in events] == [
            "assistant_delta",
            "approval_required",
            "tool_call_started",
            "tool_call_finished",
        ]
        assert events[0].data["text"] == "hello"
        assert events[1].data["action_name"] == "edit_file"
        assert events[2].data["name"] == "search"
        assert events[3].data["result_summary"] == "done"

    @pytest.mark.asyncio
    async def test_stream_uses_end_output_when_no_chunks_emitted(self) -> None:
        """If stream chunks did not arrive, use the final output text."""
        output = MagicMock()
        output.content = [{"type": "text", "text": "final text"}]

        graph = MagicMock()

        async def fake_astream_events(*args, **kwargs):
            yield {
                "event": "on_chat_model_end",
                "data": {"output": output},
            }

        graph.astream_events = fake_astream_events

        events = []
        async for event in stream_deepagents_graph_events(
            graph=graph,
            input_payload={"messages": ["msg"]},
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "assistant_delta"
        assert events[0].data["text"] == "final text"
