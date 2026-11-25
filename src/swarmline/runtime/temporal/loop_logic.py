"""Deterministic agent-loop driver — the brain of ``AgentLoopWorkflow``.

Pure control flow over injected async callbacks: no IO, no clocks, no
randomness, no temporalio imports. Inside the workflow the callbacks map to
``workflow.execute_activity``; in tests they are plain fakes. Keeping the
loop here makes the workflow logic unit-testable without a Temporal server.

Message-append semantics mirror the thin runtime's ReAct loop: the raw model
envelope goes back as an assistant turn, the tool result as a
``Result <tool>: ...`` user turn; ``new_messages`` records the
assistant/tool message pair per call for session history.

HITL: when a tool step comes back with ``needs_approval=True`` (the worker's
approval policy gated it without executing), the driver asks the injected
``wait_approval`` callback for an :class:`ApprovalDecision` — inside the
workflow that is a durable ``workflow.wait_condition`` on the approval
signal. Approved calls re-dispatch with ``approved=True`` (and any arg
modifications); denials and timeouts become a failed tool result the model
can react to, never a run failure.

Reference history: with ``inp.use_reference_history`` and an injected
``append_history`` callback, the driver never carries the conversation —
it seeds the store once, sends only revision numbers to LLM steps, and
appends per-turn deltas. At the ``continue_after_iterations`` boundary it
returns ``status="continue"`` with all resume state (revision, counters,
accumulated outputs) so the workflow can roll over via continue-as-new.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Any

from swarmline.runtime.temporal.payloads import (
    AgentRunInput,
    AgentRunResult,
    ApprovalDecision,
    EventDict,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
)

LlmStepFn = Callable[[LlmStepInput], Awaitable[LlmStepOutput]]
ToolStepFn = Callable[[ToolStepInput], Awaitable[ToolStepOutput]]
# wait_approval(step, gated_output) -> decision, or None on expiry.
ApprovalWaitFn = Callable[
    [ToolStepInput, ToolStepOutput], Awaitable[ApprovalDecision | None]
]
# append_history(delta_messages, expected_revision) -> new revision.
HistoryAppendFn = Callable[[list[dict[str, Any]], int], Awaitable[int]]


async def drive_agent_loop(
    inp: AgentRunInput,
    call_llm: LlmStepFn,
    call_tool: ToolStepFn,
    wait_approval: ApprovalWaitFn | None = None,
    append_history: HistoryAppendFn | None = None,
) -> AgentRunResult:
    """Run the ReAct loop: model decides, tools execute, until final/limits."""
    append = append_history if inp.use_reference_history else None
    reference = append is not None
    revision = inp.history_revision
    lm_messages: list[dict[str, Any]] = (
        [] if reference else [dict(m) for m in inp.messages]
    )
    if append is not None and revision < 0:
        revision = await append(inp.messages, -1)  # seed the store once

    new_messages: list[dict[str, object]] = list(inp.carried_new_messages)
    events: list[EventDict] = list(inp.carried_events)
    tool_calls_count = inp.tool_calls_used
    iterations = inp.start_iteration

    def _result(
        *,
        text: str = "",
        status: str = "ok",
        error_kind: str = "",
        error_message: str = "",
    ) -> AgentRunResult:
        return AgentRunResult(
            text=text,
            new_messages=new_messages,
            events=events,
            iterations=iterations,
            tool_calls=tool_calls_count,
            status=status,
            error_kind=error_kind,
            error_message=error_message,
            history_revision=revision,
        )

    while iterations < inp.max_iterations:
        if (
            reference
            and inp.continue_after_iterations > 0
            and iterations - inp.start_iteration >= inp.continue_after_iterations
        ):
            # Segment boundary: hand resume state to the workflow, which
            # rolls over via continue-as-new (fresh workflow history).
            return _result(status="continue")

        iterations += 1
        llm_out = await call_llm(
            LlmStepInput(
                run_id=inp.run_id,
                iteration=iterations,
                messages=lm_messages,
                system_prompt=inp.system_prompt,
                tools=inp.tools,
                model=inp.model,
                stream_events=inp.stream_events,
                history_revision=revision if reference else -1,
            )
        )
        events.extend(llm_out.events)

        if llm_out.kind == "error":
            return _result(
                status="error",
                error_kind=llm_out.error_kind or "bad_model_output",
                error_message=llm_out.error_message or "LLM step failed",
            )

        if llm_out.kind == "final":
            new_messages.append({"role": "assistant", "content": llm_out.text})
            return _result(text=llm_out.text)

        # kind == "tool_call"
        if tool_calls_count + 1 > inp.max_tool_calls:
            return _result(
                status="error",
                error_kind="budget_exceeded",
                error_message=(
                    f"Tool call budget exhausted ({inp.max_tool_calls} calls)"
                ),
            )

        step = ToolStepInput(
            run_id=inp.run_id,
            iteration=iterations,
            name=llm_out.tool_name,
            args=llm_out.tool_args,
            correlation_id=llm_out.correlation_id,
            stream_events=inp.stream_events,
        )
        tool_out = await call_tool(step)
        tool_calls_count += 1
        events.extend(tool_out.events)

        if tool_out.needs_approval:
            tool_out = await _arbitrate_approval(
                step, tool_out, call_tool, wait_approval, events
            )
            events.extend(tool_out.events)

        delta: list[dict[str, Any]] = [
            {"role": "assistant", "content": llm_out.raw},
            {"role": "user", "content": f"Result {tool_out.name}: {tool_out.result}"},
        ]
        if append is not None:
            revision = await append(delta, revision)
        else:
            lm_messages.extend(delta)
        new_messages.append(
            {
                "role": "assistant",
                "content": llm_out.assistant_message,
                "tool_calls": [
                    {
                        "id": tool_out.correlation_id,
                        "name": tool_out.name,
                        "args": llm_out.tool_args,
                    }
                ],
            }
        )
        new_messages.append(
            {"role": "tool", "content": tool_out.result, "name": tool_out.name}
        )

    return _result(
        status="error",
        error_kind="loop_limit",
        error_message=f"Max iterations exceeded ({inp.max_iterations})",
    )


async def _arbitrate_approval(
    step: ToolStepInput,
    gated: ToolStepOutput,
    call_tool: ToolStepFn,
    wait_approval: ApprovalWaitFn | None,
    events: list[EventDict],
) -> ToolStepOutput:
    """Resolve a policy-gated tool call: wait for a decision, then execute
    (approved) or synthesize a failed tool result (denied / expired).

    The ``approval_resolved`` event is appended to ``events`` here; the
    returned output carries only its own execution events (if any).
    """
    decision = await wait_approval(step, gated) if wait_approval is not None else None
    approved = decision is not None and decision.approved
    reason = (
        decision.reason
        if decision is not None
        else "approval timed out or no approval channel is configured"
    )
    events.append(
        {
            "id": f"{step.run_id}:{step.iteration}:approval:1",
            "type": "approval_resolved",
            "data": {
                "correlation_id": step.correlation_id,
                "name": step.name,
                "approved": approved,
                "reason": reason,
            },
        }
    )

    if decision is not None and decision.approved:
        args = dict(step.args)
        args.update(decision.modifications)
        return await call_tool(dataclasses.replace(step, args=args, approved=True))

    denial = reason or "no reason given"
    return ToolStepOutput(
        name=step.name,
        correlation_id=step.correlation_id,
        ok=False,
        result=json.dumps(
            {"error": f"Tool call was not approved: {denial}"}, ensure_ascii=False
        ),
    )
