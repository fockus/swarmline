"""Worker bootstrap for the Temporal runtime.

A worker owns the non-deterministic side of the agent loop: LLM credentials,
local tools, MCP servers, and the optional streaming publisher. Scale by
running more workers on the same task queue.

Programmatic::

    from temporalio.client import Client
    from swarmline.runtime.temporal.worker import build_worker

    client = await Client.connect("temporal:7233", namespace="agents")
    worker = build_worker(client, options, local_tools={"search": search_fn})
    await worker.run()

Or in one call (connect + build + run)::

    from swarmline.runtime.temporal.worker import run_worker

    await run_worker(options, local_tools={"search": search_fn})
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swarmline.runtime.temporal.activities import AgentActivities, LlmCallFn
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.stream import RunEventPublisher
from swarmline.runtime.temporal.workflow import AgentLoopWorkflow
from swarmline.runtime.types import RuntimeConfig


def build_activities(
    *,
    local_tools: dict[str, Callable[..., Any]] | None = None,
    mcp_servers: dict[str, Any] | None = None,
    llm_call: LlmCallFn | None = None,
    base_config: RuntimeConfig | None = None,
    event_bus: Any = None,
    approval_policy: Any = None,
    history_store: Any = None,
    compaction_config: Any = None,
    tool_timeout_seconds: float = 120.0,
) -> AgentActivities:
    """Assemble worker activities from swarmline components."""
    from swarmline.runtime.thin.executor import ToolExecutor

    executor = ToolExecutor(
        local_tools=local_tools,
        mcp_servers=mcp_servers,
        timeout_seconds=tool_timeout_seconds,
    )
    publisher = RunEventPublisher(event_bus) if event_bus is not None else None
    return AgentActivities(
        tool_executor=executor,
        llm_call=llm_call,
        base_config=base_config,
        publisher=publisher,
        approval_policy=approval_policy,
        history_store=history_store,
        compaction_config=compaction_config,
    )


def build_worker(
    client: Any,
    options: TemporalRuntimeOptions | None = None,
    *,
    local_tools: dict[str, Callable[..., Any]] | None = None,
    mcp_servers: dict[str, Any] | None = None,
    llm_call: LlmCallFn | None = None,
    base_config: RuntimeConfig | None = None,
    event_bus: Any = None,
    approval_policy: Any = None,
    history_store: Any = None,
    compaction_config: Any = None,
) -> Any:
    """Build a ``temporalio.worker.Worker`` serving the agent-loop workflow."""
    from temporalio.worker import Worker

    opts = options or TemporalRuntimeOptions()
    activities = build_activities(
        local_tools=local_tools,
        mcp_servers=mcp_servers,
        llm_call=llm_call,
        base_config=base_config,
        event_bus=event_bus,
        approval_policy=approval_policy,
        history_store=history_store,
        compaction_config=compaction_config,
        tool_timeout_seconds=opts.tool_timeout_seconds,
    )
    return Worker(
        client,
        task_queue=opts.task_queue,
        workflows=[AgentLoopWorkflow],
        activities=[
            activities.llm_step,
            activities.tool_step,
            activities.history_append,
        ],
    )


async def run_worker(
    options: TemporalRuntimeOptions | None = None,
    **build_kwargs: Any,
) -> None:
    """Connect to Temporal, build the worker, and run it until cancelled."""
    from swarmline.runtime.temporal.client import connect_client

    opts = options or TemporalRuntimeOptions()
    client = await connect_client(opts)
    worker = build_worker(client, opts, **build_kwargs)
    await worker.run()
