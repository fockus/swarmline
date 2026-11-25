"""Unit tests for durable HITL — approval arbitration in the loop driver
and the approval client. Pure fakes: no temporalio, no server.
"""

from __future__ import annotations

import json
from typing import Any

from swarmline.runtime.temporal.hitl import TemporalApprovalClient
from swarmline.runtime.temporal.loop_logic import drive_agent_loop
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import (
    APPROVAL_SIGNAL,
    PENDING_APPROVALS_QUERY,
    AgentRunInput,
    ApprovalDecision,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
)


def _run_input(**overrides: Any) -> AgentRunInput:
    defaults: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "system_prompt": "sys",
        "tools": [{"name": "calc", "description": "d", "parameters": {}}],
        "run_id": "r1",
        "model": "m1",
    }
    defaults.update(overrides)
    return AgentRunInput(**defaults)


class ScriptedLlm:
    """Returns pre-scripted step outputs, recording every input."""

    def __init__(self, outputs: list[LlmStepOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[LlmStepInput] = []

    async def __call__(self, step: LlmStepInput) -> LlmStepOutput:
        self.calls.append(step)
        return self._outputs.pop(0)


class GatedTool:
    """Mimics the tool activity under an approval policy: unapproved calls
    come back as ``needs_approval`` markers; approved calls execute."""

    def __init__(self) -> None:
        self.calls: list[ToolStepInput] = []

    async def __call__(self, step: ToolStepInput) -> ToolStepOutput:
        self.calls.append(step)
        if not step.approved:
            return ToolStepOutput(
                name=step.name,
                correlation_id=step.correlation_id,
                ok=False,
                result="",
                needs_approval=True,
                events=[
                    {
                        "id": f"{step.run_id}:{step.iteration}:approval:0",
                        "type": "approval_requested",
                        "data": {"name": step.name, "args": step.args},
                    }
                ],
            )
        return ToolStepOutput(
            name=step.name,
            correlation_id=step.correlation_id,
            ok=True,
            result="42",
            events=[
                {
                    "id": f"{step.run_id}:{step.iteration}:tool:1",
                    "type": "tool_call_finished",
                    "data": {"name": step.name, "ok": True},
                }
            ],
        )


def _tool_call() -> LlmStepOutput:
    return LlmStepOutput(
        kind="tool_call",
        raw='{"type": "tool_call"}',
        assistant_message="calling",
        tool_name="calc",
        tool_args={"x": 1},
        correlation_id="c1",
    )


def _final(text: str = "done") -> LlmStepOutput:
    return LlmStepOutput(kind="final", text=text)


def _approve(**decision_kwargs: Any) -> Any:
    async def _wait(step: ToolStepInput, gated: ToolStepOutput) -> ApprovalDecision:
        return ApprovalDecision(
            correlation_id=step.correlation_id, approved=True, **decision_kwargs
        )

    return _wait


class TestApprovalArbitration:
    async def test_approved_call_executes_and_counts_once(self) -> None:
        llm = ScriptedLlm([_tool_call(), _final()])
        tool = GatedTool()

        result = await drive_agent_loop(_run_input(), llm, tool, _approve())

        assert result.status == "ok"
        assert result.text == "done"
        assert result.tool_calls == 1  # probe + approved dispatch = one logical call
        assert [step.approved for step in tool.calls] == [False, True]
        types = [e["type"] for e in result.events]
        assert "approval_requested" in types
        assert "tool_call_finished" in types
        resolved = next(e for e in result.events if e["type"] == "approval_resolved")
        assert resolved["data"]["approved"] is True
        # The model saw the real tool result
        tool_message = next(m for m in result.new_messages if m["role"] == "tool")
        assert tool_message["content"] == "42"

    async def test_modifications_merge_into_approved_args(self) -> None:
        llm = ScriptedLlm([_tool_call(), _final()])
        tool = GatedTool()

        await drive_agent_loop(
            _run_input(), llm, tool, _approve(modifications={"x": 5, "safe": True})
        )

        assert tool.calls[1].args == {"x": 5, "safe": True}

    async def test_denied_call_becomes_failed_tool_result(self) -> None:
        async def deny(step: ToolStepInput, gated: ToolStepOutput) -> ApprovalDecision:
            return ApprovalDecision(
                correlation_id=step.correlation_id, approved=False, reason="too risky"
            )

        llm = ScriptedLlm([_tool_call(), _final("ok, skipping")])
        tool = GatedTool()

        result = await drive_agent_loop(_run_input(), llm, tool, deny)

        assert result.status == "ok"  # denial never fails the run
        assert result.text == "ok, skipping"
        assert len(tool.calls) == 1  # never executed
        resolved = next(e for e in result.events if e["type"] == "approval_resolved")
        assert resolved["data"]["approved"] is False
        assert resolved["data"]["reason"] == "too risky"
        # The model saw the denial and could react
        followup = llm.calls[1].messages[-1]["content"]
        assert "not approved" in followup
        assert "too risky" in followup
        tool_message = next(m for m in result.new_messages if m["role"] == "tool")
        assert "too risky" in json.loads(tool_message["content"])["error"]

    async def test_expired_approval_denies_with_timeout_reason(self) -> None:
        async def expired(step: ToolStepInput, gated: ToolStepOutput) -> None:
            return None  # workflow's durable timer fired

        llm = ScriptedLlm([_tool_call(), _final()])
        tool = GatedTool()

        result = await drive_agent_loop(_run_input(), llm, tool, expired)

        assert len(tool.calls) == 1
        resolved = next(e for e in result.events if e["type"] == "approval_resolved")
        assert resolved["data"]["approved"] is False
        assert "timed out" in resolved["data"]["reason"]

    async def test_no_approval_channel_denies(self) -> None:
        llm = ScriptedLlm([_tool_call(), _final()])
        tool = GatedTool()

        result = await drive_agent_loop(_run_input(), llm, tool, wait_approval=None)

        assert len(tool.calls) == 1
        resolved = next(e for e in result.events if e["type"] == "approval_resolved")
        assert resolved["data"]["approved"] is False


class FakeApprovalHandle:
    def __init__(self) -> None:
        self.signals: list[tuple[str, Any]] = []
        self.queried: list[str] = []

    async def signal(self, name: str, arg: Any) -> None:
        self.signals.append((name, arg))

    async def query(self, name: str) -> list[dict[str, Any]]:
        self.queried.append(name)
        return [{"correlation_id": "c1", "name": "calc"}]


class FakeTemporalClient:
    def __init__(self, handle: FakeApprovalHandle) -> None:
        self._handle = handle
        self.requested_ids: list[str] = []

    def get_workflow_handle(
        self, workflow_id: str, **kwargs: Any
    ) -> FakeApprovalHandle:
        self.requested_ids.append(workflow_id)
        return self._handle


class TestTemporalApprovalClient:
    async def test_approve_signals_workflow_by_run_id(self) -> None:
        handle = FakeApprovalHandle()
        client = FakeTemporalClient(handle)
        approvals = TemporalApprovalClient(client=client)

        await approvals.approve("r1", "c1", reason="ok", modifications={"x": 2})

        assert client.requested_ids == ["swarmline-agent-r1"]
        name, decision = handle.signals[0]
        assert name == APPROVAL_SIGNAL
        assert decision == ApprovalDecision(
            correlation_id="c1", approved=True, reason="ok", modifications={"x": 2}
        )

    async def test_deny_signals_denial(self) -> None:
        handle = FakeApprovalHandle()
        approvals = TemporalApprovalClient(client=FakeTemporalClient(handle))

        await approvals.deny("r1", "c1", reason="no")

        _, decision = handle.signals[0]
        assert decision.approved is False
        assert decision.reason == "no"

    async def test_pending_queries_workflow(self) -> None:
        handle = FakeApprovalHandle()
        approvals = TemporalApprovalClient(client=FakeTemporalClient(handle))

        pending = await approvals.pending("r1")

        assert handle.queried == [PENDING_APPROVALS_QUERY]
        assert pending[0]["correlation_id"] == "c1"

    async def test_workflow_id_prefix_from_options(self) -> None:
        handle = FakeApprovalHandle()
        client = FakeTemporalClient(handle)
        approvals = TemporalApprovalClient(
            client=client,
            options=TemporalRuntimeOptions(workflow_id_prefix="prod-agent-"),
        )

        await approvals.deny("r7", "c1")

        assert client.requested_ids == ["prod-agent-r7"]
