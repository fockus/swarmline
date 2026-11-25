"""build_supervisor — assemble the 5 supervisor tools onto a kernel-backed agent.

H6 supervisor-orchestrator, Task 2 (REQ-001, REQ-002). The supervisor is a
plain agent on the `ExecutionKernel` contract (REQ-002) — no bespoke
supervisor loop. `ThinRuntime` is the existing "agent = kernel + tools"
construction path: it dispatches `.run()` to an `ExecutionKernel` resolved
from `get_default_kernel_registry()` (see `runtime/thin/runtime.py`).

`ThinRuntime` is imported LAZILY inside `build_supervisor` (not at module
level) so importing `orchestration.supervisor` for just `Blackboard`/
`SupervisorState` never eagerly pulls the ThinRuntime import chain (I-020).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from swarmline.orchestration.supervisor.finalize import (
    FINALIZE_TOOL_SPEC,
    create_finalize_tool,
)
from swarmline.orchestration.supervisor.handoff_tool import (
    HANDOFF_TOOL_SPEC,
    create_handoff_tool,
)
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.tools import (
    READ_REPORTS_TOOL_SPEC,
    SEND_MESSAGE_TOOL_SPEC,
    SPAWN_SUBAGENT_TOOL_SPEC,
    UPDATE_PLAN_TOOL_SPEC,
    SubagentSpawner,
    create_read_reports_tool,
    create_send_message_tool,
    create_spawn_subagent_tool,
    create_update_plan_tool,
)
from swarmline.runtime.types import RuntimeConfig, ToolSpec

if TYPE_CHECKING:
    from swarmline.orchestration.supervisor.handoff import GraphHandoffRunner
    from swarmline.protocols.verification import Verifier
    from swarmline.runtime.thin.runtime import ThinRuntime
    from swarmline.types import VerificationLedger

ToolExecutorFn = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class SupervisorKernel:
    """The assembled supervisor: a kernel-backed runtime plus its tool surface.

    `active_tools`/`local_tools` are exposed alongside `runtime` so callers
    (and tests) can inspect/assert on the assembled tool set without reaching
    into `ThinRuntime`'s private construction internals.
    """

    runtime: ThinRuntime
    active_tools: list[ToolSpec]
    local_tools: dict[str, ToolExecutorFn]


def build_supervisor(
    state: SupervisorState,
    orchestrator: SubagentSpawner,
    *,
    config: RuntimeConfig | None = None,
    llm_call: Callable[..., Any] | None = None,
    verifier: Verifier | None = None,
    ledger: VerificationLedger | None = None,
    handoff_runner: GraphHandoffRunner | None = None,
) -> SupervisorKernel:
    """Construct the supervisor: the 5 tools bound to `state`/`orchestrator`.

    The supervisor is a `ThinRuntime` — REQ-002's "standard kernel" contract
    is satisfied because `ThinRuntime.run()` dispatches to an
    `ExecutionKernel` resolved from the default kernel registry, not a
    bespoke supervisor loop.

    `verifier`/`ledger` are OPT-IN (REQ-011/REQ-012): both default to
    `None`, in which case `finalize` behaves exactly as it always has (a
    plain summary). Supplying both wires the verify-before-done contract
    gate onto the assembled `finalize` tool — see
    `finalize.create_finalize_tool` for the gate semantics.

    `handoff_runner` is OPT-IN too (kernel-wiring Task 3, REQ-009/010): it
    defaults to `None`, in which case the assembled tool set is EXACTLY the
    5 tools above — unchanged (REQ-010). Supplying a `GraphHandoffRunner`
    appends a 6th `handoff` tool wired to the existing `handoff()` primitive
    via `handoff_tool.create_handoff_tool` — see that module for the
    executor's arg-mapping semantics.
    """
    from swarmline.runtime.thin.runtime import ThinRuntime

    active_tools: list[ToolSpec] = [
        SPAWN_SUBAGENT_TOOL_SPEC,
        UPDATE_PLAN_TOOL_SPEC,
        SEND_MESSAGE_TOOL_SPEC,
        READ_REPORTS_TOOL_SPEC,
        FINALIZE_TOOL_SPEC,
    ]
    local_tools: dict[str, ToolExecutorFn] = {
        "spawn_subagent": create_spawn_subagent_tool(state, orchestrator),
        "update_plan": create_update_plan_tool(state),
        "send_message": create_send_message_tool(state),
        "read_reports": create_read_reports_tool(state),
        "finalize": create_finalize_tool(state, verifier=verifier, ledger=ledger),
    }
    if handoff_runner is not None:
        active_tools.append(HANDOFF_TOOL_SPEC)
        local_tools["handoff"] = create_handoff_tool(handoff_runner)
    runtime = ThinRuntime(config=config, llm_call=llm_call, local_tools=local_tools)
    return SupervisorKernel(
        runtime=runtime, active_tools=active_tools, local_tools=local_tools
    )
