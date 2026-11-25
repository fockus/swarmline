"""Unit tests for the Temporal runtime's deterministic loop driver.

``drive_agent_loop`` is pure control flow over injected callbacks — these
tests need no temporalio and no server.
"""

from __future__ import annotations

from typing import Any

from swarmline.domain_types import Message
from swarmline.runtime.temporal.loop_logic import drive_agent_loop
from swarmline.runtime.temporal.payloads import (
    AgentRunInput,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
    message_from_dict,
    message_to_dict,
)


def _run_input(**overrides: Any) -> AgentRunInput:
    defaults: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "system_prompt": "be helpful",
        "tools": [{"name": "calc", "description": "", "parameters": {}}],
        "run_id": "r1",
        "model": "m1",
        "max_iterations": 5,
        "max_tool_calls": 3,
    }
    defaults.update(overrides)
    return AgentRunInput(**defaults)


def _final(text: str) -> LlmStepOutput:
    return LlmStepOutput(
        kind="final",
        text=text,
        events=[{"id": "e", "type": "assistant_delta", "data": {"text": text}}],
    )


def _tool_call(name: str = "calc", cid: str = "c1") -> LlmStepOutput:
    return LlmStepOutput(
        kind="tool_call",
        raw='{"type": "tool_call"}',
        tool_name=name,
        tool_args={"x": 1},
        correlation_id=cid,
        assistant_message="calling",
    )


async def _no_tool(step: ToolStepInput) -> ToolStepOutput:
    raise AssertionError("tool must not be called")


class TestDriveAgentLoop:
    async def test_immediate_final(self) -> None:
        async def llm(step: LlmStepInput) -> LlmStepOutput:
            assert step.iteration == 1
            assert step.model == "m1"
            return _final("done")

        result = await drive_agent_loop(_run_input(), llm, _no_tool)

        assert result.status == "ok"
        assert result.text == "done"
        assert result.iterations == 1
        assert result.tool_calls == 0
        assert result.new_messages == [{"role": "assistant", "content": "done"}]
        assert [e["type"] for e in result.events] == ["assistant_delta"]

    async def test_tool_then_final_threads_result_into_messages(self) -> None:
        seen_messages: list[list[dict[str, Any]]] = []

        async def llm(step: LlmStepInput) -> LlmStepOutput:
            seen_messages.append(step.messages)
            if step.iteration == 1:
                return _tool_call()
            return _final("42")

        async def tool(step: ToolStepInput) -> ToolStepOutput:
            assert step.name == "calc"
            assert step.args == {"x": 1}
            return ToolStepOutput(
                name="calc", correlation_id=step.correlation_id, ok=True, result="41+1"
            )

        result = await drive_agent_loop(_run_input(), llm, tool)

        assert result.status == "ok"
        assert result.text == "42"
        assert result.iterations == 2
        assert result.tool_calls == 1
        # Second LLM call sees the raw envelope + the tool result turn
        second = seen_messages[1]
        assert second[-2] == {"role": "assistant", "content": '{"type": "tool_call"}'}
        assert second[-1] == {"role": "user", "content": "Result calc: 41+1"}
        # Session history records the assistant tool_call and the tool result
        assert result.new_messages[0]["tool_calls"][0]["name"] == "calc"
        assert result.new_messages[1] == {
            "role": "tool",
            "content": "41+1",
            "name": "calc",
        }

    async def test_loop_limit(self) -> None:
        async def llm(step: LlmStepInput) -> LlmStepOutput:
            return _tool_call(cid=f"c{step.iteration}")

        async def tool(step: ToolStepInput) -> ToolStepOutput:
            return ToolStepOutput(
                name=step.name, correlation_id=step.correlation_id, ok=True, result="r"
            )

        result = await drive_agent_loop(_run_input(max_iterations=2), llm, tool)

        assert result.status == "error"
        assert result.error_kind == "loop_limit"
        assert result.iterations == 2

    async def test_tool_budget_exceeded(self) -> None:
        async def llm(step: LlmStepInput) -> LlmStepOutput:
            return _tool_call()

        async def tool(step: ToolStepInput) -> ToolStepOutput:
            return ToolStepOutput(
                name=step.name, correlation_id=step.correlation_id, ok=True, result="r"
            )

        result = await drive_agent_loop(
            _run_input(max_iterations=10, max_tool_calls=1), llm, tool
        )

        assert result.status == "error"
        assert result.error_kind == "budget_exceeded"
        assert result.tool_calls == 1

    async def test_llm_error_stops_loop(self) -> None:
        async def llm(step: LlmStepInput) -> LlmStepOutput:
            return LlmStepOutput(
                kind="error", error_kind="bad_model_output", error_message="garbage"
            )

        result = await drive_agent_loop(_run_input(), llm, _no_tool)

        assert result.status == "error"
        assert result.error_kind == "bad_model_output"
        assert result.error_message == "garbage"

    async def test_events_accumulate_in_order(self) -> None:
        async def llm(step: LlmStepInput) -> LlmStepOutput:
            if step.iteration == 1:
                out = _tool_call()
                out.events = [{"id": "l1", "type": "status", "data": {}}]
                return out
            return _final("ok")

        async def tool(step: ToolStepInput) -> ToolStepOutput:
            return ToolStepOutput(
                name=step.name,
                correlation_id=step.correlation_id,
                ok=True,
                result="r",
                events=[
                    {"id": "t1", "type": "tool_call_started", "data": {}},
                    {"id": "t2", "type": "tool_call_finished", "data": {}},
                ],
            )

        result = await drive_agent_loop(_run_input(), llm, tool)

        assert [e["id"] for e in result.events] == ["l1", "t1", "t2", "e"]


class TestMessageSerialization:
    def test_roundtrip_preserves_fields(self) -> None:
        message = Message(
            role="tool",
            content="result",
            name="calc",
            tool_calls=[{"id": "c1", "name": "calc", "args": {}}],
            metadata={"k": "v"},
        )
        assert message_from_dict(message_to_dict(message)) == message

    def test_minimal_message_omits_optional_fields(self) -> None:
        data = message_to_dict(Message(role="user", content="hi"))
        assert data == {"role": "user", "content": "hi"}
