"""Temporal durable runtime (experimental) — ``swarmline[temporal]``.

Implements the design in ``docs/proposals/temporal-runtime.md``: the agent
loop runs as a deterministic Temporal workflow; every LLM call and tool call
is a Temporal activity executed on a worker fleet. A single agent run
survives worker crashes and deploys, resuming from the last completed step.

Client side (no tools/LLM here — they live on workers)::

    from swarmline.runtime.temporal import TemporalAgentRuntime, TemporalRuntimeOptions

    runtime = TemporalAgentRuntime(
        config,
        options=TemporalRuntimeOptions(address="temporal:7233", task_queue="agents"),
    )

Worker side::

    from swarmline.runtime.temporal.worker import run_worker

    await run_worker(options, local_tools={...}, mcp_servers={...})

Durable HITL (any process holding a Temporal client)::

    from swarmline.runtime.temporal import TemporalApprovalClient

    approvals = TemporalApprovalClient(options=options)
    await approvals.approve(run_id, correlation_id)

Light exports (``options``, ``payloads``, ``loop_logic``, ``stream``,
``state``, ``eval_export``) do not require ``temporalio``; the
workflow/activities/worker/runtime/hitl/codec modules do.
"""

from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import (
    AgentRunInput,
    AgentRunResult,
    ApprovalDecision,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
)
from swarmline.runtime.temporal.state import (
    HistoryStore,
    InMemoryHistoryStore,
    MessageStoreHistoryAdapter,
)

__all__ = [
    "AgentActivities",
    "AgentLoopWorkflow",
    "AgentRunInput",
    "AgentRunResult",
    "ApprovalDecision",
    "HistoryStore",
    "InMemoryHistoryStore",
    "LlmStepInput",
    "LlmStepOutput",
    "MessageStoreHistoryAdapter",
    "TemporalAgentRuntime",
    "TemporalApprovalClient",
    "TemporalRuntimeOptions",
    "ToolStepInput",
    "ToolStepOutput",
]


def __getattr__(name: str) -> object:
    if name == "TemporalAgentRuntime":
        from swarmline.runtime.temporal.runtime import TemporalAgentRuntime

        return TemporalAgentRuntime
    if name == "AgentLoopWorkflow":
        from swarmline.runtime.temporal.workflow import AgentLoopWorkflow

        return AgentLoopWorkflow
    if name == "AgentActivities":
        from swarmline.runtime.temporal.activities import AgentActivities

        return AgentActivities
    if name == "TemporalApprovalClient":
        from swarmline.runtime.temporal.hitl import TemporalApprovalClient

        return TemporalApprovalClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
