"""Unit tests for the Temporal runtime's activities and workflow definition.

Activities are plain async methods (no activity context APIs used), so they
are called directly with fake LLM/tool dependencies. Requires temporalio
(``pip install swarmline[temporal]``) — skipped otherwise.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("temporalio")

from swarmline.observability.event_bus import InMemoryEventBus  # noqa: E402
from swarmline.runtime.temporal.activities import AgentActivities  # noqa: E402
from swarmline.runtime.temporal.payloads import (  # noqa: E402
    LlmStepInput,
    ToolStepInput,
)
from swarmline.runtime.temporal.stream import (  # noqa: E402
    RunEventPublisher,
    RunEventSubscriber,
)
from swarmline.runtime.thin.executor import ToolExecutor  # noqa: E402

_TOOL_SCHEMA = [{"name": "calc", "description": "adds", "parameters": {}}]


def _llm_returning(text: str) -> Any:
    async def _call(
        messages: list[dict[str, str]], system_prompt: str, model: str
    ) -> str:
        return text

    return _call


def _activities(llm_text: str, **kwargs: Any) -> AgentActivities:
    async def calc(args: dict[str, Any]) -> str:
        return str(args.get("x", 0) + 1)

    executor = ToolExecutor(local_tools={"calc": calc})
    return AgentActivities(
        tool_executor=executor, llm_call=_llm_returning(llm_text), **kwargs
    )


def _llm_input(**overrides: Any) -> LlmStepInput:
    defaults: dict[str, Any] = {
        "run_id": "r1",
        "iteration": 1,
        "messages": [{"role": "user", "content": "hi"}],
        "system_prompt": "sys",
        "tools": _TOOL_SCHEMA,
        "model": "m1",
    }
    defaults.update(overrides)
    return LlmStepInput(**defaults)


class TestLlmStep:
    async def test_final_envelope(self) -> None:
        acts = _activities('{"type": "final", "final_message": "hello"}')

        out = await acts.llm_step(_llm_input())

        assert out.kind == "final"
        assert out.text == "hello"
        assert out.events[0]["type"] == "assistant_delta"
        assert out.events[0]["id"] == "r1:1:llm:0"

    async def test_tool_call_envelope(self) -> None:
        raw = json.dumps(
            {
                "type": "tool_call",
                "tool": {"name": "calc", "args": {"x": 1}, "correlation_id": "c7"},
                "assistant_message": "calculating",
            }
        )
        acts = _activities(raw)

        out = await acts.llm_step(_llm_input())

        assert out.kind == "tool_call"
        assert out.tool_name == "calc"
        assert out.tool_args == {"x": 1}
        assert out.correlation_id == "c7"
        assert out.raw == raw
        assert out.events[0]["data"]["text"] == "calculating"

    async def test_no_tools_is_conversational(self) -> None:
        acts = _activities("plain answer")

        out = await acts.llm_step(_llm_input(tools=[]))

        assert out.kind == "final"
        assert out.text == "plain answer"

    async def test_non_envelope_text_falls_back_to_final(self) -> None:
        acts = _activities("Just prose, no JSON.")

        out = await acts.llm_step(_llm_input())

        assert out.kind == "final"
        assert out.text == "Just prose, no JSON."

    async def test_unparseable_json_is_bad_model_output(self) -> None:
        acts = _activities('{"type": "unknown_shape"}')

        out = await acts.llm_step(_llm_input())

        assert out.kind == "error"
        assert out.error_kind == "bad_model_output"

    async def test_clarify_becomes_final_with_questions(self) -> None:
        raw = json.dumps(
            {
                "type": "clarify",
                "questions": [{"id": "q1", "text": "Which city?"}],
                "assistant_message": "Need info:",
            }
        )
        acts = _activities(raw)

        out = await acts.llm_step(_llm_input())

        assert out.kind == "final"
        assert "Which city?" in out.text
        assert "Need info:" in out.text


class TestToolStep:
    async def test_executes_local_tool(self) -> None:
        acts = _activities("unused")

        out = await acts.tool_step(
            ToolStepInput(
                run_id="r1",
                iteration=2,
                name="calc",
                args={"x": 41},
                correlation_id="c1",
            )
        )

        assert out.ok
        assert out.result == "42"
        assert [e["type"] for e in out.events] == [
            "tool_call_started",
            "tool_call_finished",
        ]
        assert out.events[0]["id"] == "r1:2:tool:0"

    async def test_unknown_tool_reports_error_result(self) -> None:
        acts = _activities("unused")

        out = await acts.tool_step(
            ToolStepInput(
                run_id="r1", iteration=1, name="nope", args={}, correlation_id="c1"
            )
        )

        assert not out.ok
        assert "error" in json.loads(out.result)


class TestStreamingPublish:
    async def test_events_published_when_streaming_enabled(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()
        acts = _activities(
            '{"type": "final", "final_message": "hi"}',
            publisher=RunEventPublisher(bus),
        )

        await acts.llm_step(_llm_input(stream_events=True))

        event = await sub.next(timeout=0.5)
        assert event is not None
        assert event["type"] == "assistant_delta"
        sub.detach()

    async def test_no_publish_when_streaming_disabled(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()
        acts = _activities(
            '{"type": "final", "final_message": "hi"}',
            publisher=RunEventPublisher(bus),
        )

        await acts.llm_step(_llm_input(stream_events=False))

        assert await sub.next(timeout=0.05) is None
        sub.detach()


class TestApprovalGating:
    def _gated_activities(self, **kwargs: Any) -> AgentActivities:
        from swarmline.hitl.policies import ToolApprovalPolicy

        return _activities(
            "unused",
            approval_policy=ToolApprovalPolicy(tools=frozenset({"calc"})),
            **kwargs,
        )

    async def test_policy_gates_without_executing(self) -> None:
        acts = self._gated_activities()

        out = await acts.tool_step(
            ToolStepInput(
                run_id="r1",
                iteration=1,
                name="calc",
                args={"x": 1},
                correlation_id="c1",
            )
        )

        assert out.needs_approval
        assert not out.ok
        assert out.result == ""
        assert out.events[0]["type"] == "approval_requested"
        assert out.events[0]["id"] == "r1:1:approval:0"
        assert out.events[0]["data"]["correlation_id"] == "c1"

    async def test_approved_redispatch_executes(self) -> None:
        acts = self._gated_activities()

        out = await acts.tool_step(
            ToolStepInput(
                run_id="r1",
                iteration=1,
                name="calc",
                args={"x": 41},
                correlation_id="c1",
                approved=True,
            )
        )

        assert not out.needs_approval
        assert out.ok
        assert out.result == "42"

    async def test_ungated_tools_execute_normally(self) -> None:
        from swarmline.hitl.policies import ToolApprovalPolicy

        acts = _activities(
            "unused", approval_policy=ToolApprovalPolicy(tools=frozenset({"other"}))
        )

        out = await acts.tool_step(
            ToolStepInput(
                run_id="r1",
                iteration=1,
                name="calc",
                args={"x": 1},
                correlation_id="c1",
            )
        )

        assert not out.needs_approval
        assert out.ok

    async def test_approval_request_published_when_streaming(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()
        acts = self._gated_activities(publisher=RunEventPublisher(bus))

        await acts.tool_step(
            ToolStepInput(
                run_id="r1",
                iteration=1,
                name="calc",
                args={},
                correlation_id="c1",
                stream_events=True,
            )
        )

        event = await sub.next(timeout=0.5)
        assert event is not None
        assert event["type"] == "approval_requested"
        sub.detach()


class TestReferenceHistoryActivities:
    def _recording_llm(self) -> Any:
        calls: list[list[dict[str, str]]] = []

        async def _call(
            messages: list[dict[str, str]], system_prompt: str, model: str
        ) -> str:
            calls.append(messages)
            return '{"type": "final", "final_message": "ok"}'

        _call.calls = calls  # type: ignore[attr-defined]
        return _call

    async def test_llm_step_materializes_from_store(self) -> None:
        from swarmline.runtime.temporal.state import InMemoryHistoryStore

        store = InMemoryHistoryStore()
        await store.append(
            "r1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "thinking"},
            ],
        )
        llm = self._recording_llm()
        acts = AgentActivities(
            tool_executor=ToolExecutor(local_tools={}),
            llm_call=llm,
            history_store=store,
        )

        out = await acts.llm_step(_llm_input(messages=[], history_revision=2))

        assert out.kind == "final"
        assert [m["role"] for m in llm.calls[0]] == ["user", "assistant"]

    async def test_llm_step_without_store_fails_non_retryable(self) -> None:
        from temporalio.exceptions import ApplicationError

        acts = _activities("unused")

        with pytest.raises(ApplicationError, match="history_store") as exc_info:
            await acts.llm_step(_llm_input(messages=[], history_revision=2))
        assert exc_info.value.non_retryable

    async def test_history_append_activity_is_idempotent(self) -> None:
        from swarmline.runtime.temporal.payloads import HistoryAppendInput
        from swarmline.runtime.temporal.state import InMemoryHistoryStore

        store = InMemoryHistoryStore()
        acts = _activities("unused", history_store=store)
        delta = HistoryAppendInput(
            run_id="r1",
            messages=[{"role": "user", "content": "hi"}],
            expected_revision=0,
        )

        first = await acts.history_append(delta)
        retry = await acts.history_append(delta)  # redelivery after retry

        assert first.revision == retry.revision == 1
        assert len(await store.load("r1")) == 1

    async def test_compaction_shrinks_materialized_history(self) -> None:
        from swarmline.compaction import CompactionConfig
        from swarmline.runtime.temporal.state import InMemoryHistoryStore

        store = InMemoryHistoryStore()
        long_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "word " * 200}
            for i in range(20)
        ]
        await store.append("r1", long_history)
        llm = self._recording_llm()
        acts = AgentActivities(
            tool_executor=ToolExecutor(local_tools={}),
            llm_call=llm,
            history_store=store,
            compaction_config=CompactionConfig(threshold_tokens=300),
        )

        await acts.llm_step(_llm_input(messages=[], history_revision=20))

        assert len(llm.calls[0]) < 20  # oldest messages compacted away
        assert len(await store.load("r1")) == 20  # the store is never rewritten


class TestWorkflowDefinition:
    def test_workflow_module_defines_temporal_workflow(self) -> None:
        from swarmline.runtime.temporal.workflow import AgentLoopWorkflow

        assert hasattr(AgentLoopWorkflow, "__temporal_workflow_definition")

    def test_activity_methods_carry_definitions(self) -> None:
        acts = _activities("x")
        assert hasattr(acts.llm_step, "__temporal_activity_definition")
        assert hasattr(acts.tool_step, "__temporal_activity_definition")
        assert hasattr(acts.history_append, "__temporal_activity_definition")

    def test_approval_signal_and_query_definitions(self) -> None:
        from swarmline.runtime.temporal.payloads import ApprovalDecision
        from swarmline.runtime.temporal.workflow import AgentLoopWorkflow

        assert hasattr(
            AgentLoopWorkflow.resolve_approval, "__temporal_signal_definition"
        )
        assert hasattr(
            AgentLoopWorkflow.pending_approvals, "__temporal_query_definition"
        )

        wf = AgentLoopWorkflow()
        assert wf.pending_approvals() == []
        wf.resolve_approval(ApprovalDecision(correlation_id="c1", approved=True))
        assert "c1" in wf._decisions


class TestPayloadConverter:
    """Payload dataclasses survive Temporal's default JSON data converter."""

    async def test_run_input_and_result_roundtrip(self) -> None:
        from temporalio.converter import DataConverter

        from swarmline.runtime.temporal.payloads import (
            AgentRunInput,
            AgentRunResult,
            LlmStepOutput,
        )

        conv = DataConverter.default
        inp = AgentRunInput(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="sys",
            tools=[{"name": "calc", "description": "d", "parameters": {}}],
            run_id="r1",
            model="m1",
        )
        [decoded] = await conv.decode(await conv.encode([inp]), [AgentRunInput])
        assert decoded == inp

        result = AgentRunResult(
            text="t",
            new_messages=[{"role": "assistant", "content": "t"}],
            events=[{"id": "a", "type": "final", "data": {}}],
            iterations=1,
            tool_calls=0,
        )
        [decoded2] = await conv.decode(await conv.encode([result]), [AgentRunResult])
        assert decoded2 == result

        step = LlmStepOutput(
            kind="tool_call", tool_name="calc", tool_args={"x": 1}, correlation_id="c1"
        )
        [decoded3] = await conv.decode(await conv.encode([step]), [LlmStepOutput])
        assert decoded3 == step
