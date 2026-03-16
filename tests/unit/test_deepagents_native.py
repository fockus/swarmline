"""Тесты native upstream adapter для DeepAgents."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("deepagents", reason="deepagents не установлен")
from cognitia.runtime.deepagents_native import (
    build_deepagents_graph,
    stream_deepagents_graph_events,
    validate_native_backend_config,
)
from cognitia.runtime.types import ToolSpec


class TestBuildDeepAgentsGraph:
    """Сборка native upstream graph."""

    def test_build_graph_calls_create_deep_agent(self) -> None:
        """Native builder собирает upstream graph с resolved LLM и tools."""
        tools = [ToolSpec(name="search", description="Search", parameters={})]

        with (
            patch(
                "cognitia.runtime.deepagents_native.build_deepagents_chat_model",
                return_value="llm",
            ),
            patch(
                "cognitia.runtime.deepagents_native.create_langchain_tool",
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
        """Native builder не дублирует upstream built-ins и сохраняет local executor."""
        tools = [
            ToolSpec(name="Bash", description="shell", parameters={}),
            ToolSpec(name="execute", description="shell", parameters={}),
            ToolSpec(name="calc", description="Search", parameters={}, is_local=True),
        ]

        async def calc(**kwargs):
            return "42"

        with (
            patch(
                "cognitia.runtime.deepagents_native.build_deepagents_chat_model",
                return_value="llm",
            ),
            patch(
                "cognitia.runtime.deepagents_native.create_langchain_tool",
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

    def test_validate_native_backend_config_requires_backend_for_native_builtins(self) -> None:
        """Native built-ins без backend должны fail-fast."""
        error = validate_native_backend_config(
            native_tool_names=["execute", "read_file"],
            native_config={},
        )

        assert error is not None
        assert error.kind == "capability_unsupported"
        assert "backend" in error.message
        assert error.details == {"native_tools": ["execute", "read_file"]}

    def test_validate_native_backend_config_allows_no_backend_without_native_builtins(self) -> None:
        """Если native built-ins не запрошены, backend не обязателен."""
        error = validate_native_backend_config(
            native_tool_names=[],
            native_config={},
        )

        assert error is None


class TestStreamDeepAgentsGraphEvents:
    """Нормализация upstream graph events в RuntimeEvent."""

    @pytest.mark.asyncio
    async def test_stream_maps_text_and_tool_events(self) -> None:
        """Строковые chunks и tool events маппятся в RuntimeEvent."""
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
        """Если stream chunks не пришли, используем final output текст."""
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
