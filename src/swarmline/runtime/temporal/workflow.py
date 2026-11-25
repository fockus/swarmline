"""AgentLoopWorkflow — the durable, deterministic agent loop.

The workflow holds only control flow (via ``loop_logic.drive_agent_loop``);
every LLM/tool call is dispatched as an activity with its own timeout and
retry policy. Activity failures that exhaust retries are mapped to loop-level
errors instead of failing the workflow, so the client always receives a
structured ``AgentRunResult``.

HITL: a tool call gated by the worker's approval policy parks the workflow
on ``workflow.wait_condition`` until an :data:`APPROVAL_SIGNAL` arrives (or
the durable expiry timer fires — auto-deny). Pending requests survive worker
deploys and restarts and are inspectable via :data:`PENDING_APPROVALS_QUERY`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from swarmline.runtime.temporal.loop_logic import drive_agent_loop
    from swarmline.runtime.temporal.payloads import (
        APPROVAL_SIGNAL,
        HISTORY_ACTIVITY,
        LLM_ACTIVITY,
        PENDING_APPROVALS_QUERY,
        TOOL_ACTIVITY,
        WORKFLOW_NAME,
        AgentRunInput,
        AgentRunResult,
        ApprovalDecision,
        HistoryAppendInput,
        HistoryAppendOutput,
        LlmStepInput,
        LlmStepOutput,
        ToolStepInput,
        ToolStepOutput,
    )

_HISTORY_TIMEOUT = timedelta(seconds=60)
_HISTORY_RETRY_ATTEMPTS = 5  # append is idempotent (expected_revision guard)

__all__ = ["WORKFLOW_NAME", "AgentLoopWorkflow"]


def _cause_message(err: ActivityError) -> str:
    cause = err.cause
    message = getattr(cause, "message", None)
    return message if isinstance(message, str) and message else str(cause or err)


@workflow.defn(name=WORKFLOW_NAME)
class AgentLoopWorkflow:
    """One durable agent run."""

    def __init__(self) -> None:
        self._decisions: dict[str, ApprovalDecision] = {}
        self._pending: dict[str, dict[str, object]] = {}

    @workflow.signal(name=APPROVAL_SIGNAL)
    def resolve_approval(self, decision: ApprovalDecision) -> None:
        """Deliver a human decision for a pending tool call."""
        self._decisions[decision.correlation_id] = decision

    @workflow.query(name=PENDING_APPROVALS_QUERY)
    def pending_approvals(self) -> list[dict[str, object]]:
        """Tool calls currently parked on human approval."""
        return list(self._pending.values())

    @workflow.run
    async def run(self, inp: AgentRunInput) -> AgentRunResult:
        """Drive the loop; LLM/tool steps execute as activities."""

        async def call_llm(step: LlmStepInput) -> LlmStepOutput:
            try:
                return await workflow.execute_activity(
                    LLM_ACTIVITY,
                    step,
                    result_type=LlmStepOutput,
                    start_to_close_timeout=timedelta(seconds=inp.llm_timeout_seconds),
                    retry_policy=RetryPolicy(
                        maximum_attempts=max(1, inp.llm_retry_attempts)
                    ),
                )
            except ActivityError as err:
                return LlmStepOutput(
                    kind="error",
                    error_kind="runtime_crash",
                    error_message=f"LLM activity failed: {_cause_message(err)}",
                )

        async def call_tool(step: ToolStepInput) -> ToolStepOutput:
            try:
                return await workflow.execute_activity(
                    TOOL_ACTIVITY,
                    step,
                    result_type=ToolStepOutput,
                    start_to_close_timeout=timedelta(seconds=inp.tool_timeout_seconds),
                    retry_policy=RetryPolicy(
                        maximum_attempts=max(1, inp.tool_retry_attempts)
                    ),
                )
            except ActivityError as err:
                # A dead tool host is information for the model, not a run
                # failure — surface it as a failed tool result.
                return ToolStepOutput(
                    name=step.name,
                    correlation_id=step.correlation_id,
                    ok=False,
                    result=json.dumps(
                        {"error": f"Tool activity failed: {_cause_message(err)}"},
                        ensure_ascii=False,
                    ),
                )

        async def append_history(
            messages: list[dict[str, Any]], expected_revision: int
        ) -> int:
            out: HistoryAppendOutput = await workflow.execute_activity(
                HISTORY_ACTIVITY,
                HistoryAppendInput(
                    run_id=inp.run_id,
                    messages=messages,
                    expected_revision=expected_revision,
                ),
                result_type=HistoryAppendOutput,
                start_to_close_timeout=_HISTORY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=_HISTORY_RETRY_ATTEMPTS),
            )
            return out.revision

        async def wait_approval(
            step: ToolStepInput,
            gated: ToolStepOutput,  # noqa: ARG001 — event already emitted by the activity
        ) -> ApprovalDecision | None:
            correlation_id = step.correlation_id
            self._pending[correlation_id] = {
                "correlation_id": correlation_id,
                "name": step.name,
                "args": step.args,
                "iteration": step.iteration,
            }
            timeout = (
                timedelta(seconds=inp.approval_timeout_seconds)
                if inp.approval_timeout_seconds > 0
                else None
            )
            try:
                await workflow.wait_condition(
                    lambda: correlation_id in self._decisions, timeout=timeout
                )
            except asyncio.TimeoutError:
                return None
            finally:
                self._pending.pop(correlation_id, None)
            return self._decisions.pop(correlation_id)

        result = await drive_agent_loop(
            inp,
            call_llm,
            call_tool,
            wait_approval,
            append_history if inp.use_reference_history else None,
        )

        if result.status == "continue":
            # Segment boundary: fresh workflow history, same run id. The
            # conversation stays in the history store; only resume state
            # and accumulated outputs carry over.
            workflow.continue_as_new(
                dataclasses.replace(
                    inp,
                    messages=[],
                    history_revision=result.history_revision,
                    start_iteration=result.iterations,
                    tool_calls_used=result.tool_calls,
                    carried_new_messages=result.new_messages,
                    carried_events=result.events,
                )
            )

        return result
