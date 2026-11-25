"""`orchestrate` tool + recursion depth-guard (Epic G, Task 8A).

Covers REQ-019 (an `orchestrate` tool an agent can call to launch a bounded
sub-orchestration: plan -> verify -> deploy -> gate) and REQ-020 half (a
numeric recursion-depth guard). Mirrors the `ToolSpec` constant +
`create_<name>_tool(...) -> ToolExecutorFn` factory idiom from
`orchestration/supervisor/tools.py` (NOT the `@tool` decorator), with a
narrow local `@runtime_checkable Protocol` (`SubEngine`, ISP: 1 method) so
tests inject a fake `OrchestratorEngine` without its real import chain.

Depth-from-context binding: `depth` is the recursion level of the agent that
HOLDS this tool, read from the execution context by the caller at wiring
time (this module does not read any context itself — it only consumes the
already-resolved integer). Each nested sub-orchestration would wire its own
`orchestrate` tool at `depth + 1` for the agents it spawns, so recursion
depth grows by exactly one per `orchestrate` call and is bounded by
`OrchestratorConfig.max_recursion_depth`.

8B (budget-gas ceiling via a `GraphBudgetTracker`, Epic F3) is deferred:
`multi_agent/graph_budget.py` does not exist in this tree, so no budget-gas
refusal is implemented here. The numeric depth guard alone bounds runaway
recursion until F3 lands; do NOT fabricate a `GraphBudgetTracker`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from swarmline.orchestration.autopilot.types import (
    OrchestrationResult,
    OrchestratorConfig,
)
from swarmline.runtime.types import ToolSpec

ToolExecutorFn = Callable[[dict[str, Any]], Awaitable[str]]


@runtime_checkable
class SubEngine(Protocol):
    """Minimal duck-typed contract the `orchestrate` tool needs.

    Deliberately narrower than `OrchestratorEngine` (ISP: 1 method) so tests
    can inject a fake without pulling in the real engine's planner/verify/
    deploy/gate import chain.
    """

    async def run(
        self,
        goal: str | None = None,
        *,
        mode: str = "dynamic",
        config: OrchestratorConfig | None = None,
    ) -> OrchestrationResult:
        """Drive one plan -> verify -> deploy -> gate run for `goal`."""
        ...  # pragma: no cover


ORCHESTRATE_TOOL_SPEC = ToolSpec(
    name="orchestrate",
    description=(
        "Launch a bounded sub-orchestration for `goal` (a full "
        "plan->verify->deploy->gate run). Refused past the recursion-depth "
        "limit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The goal for the sub-orchestration.",
            }
        },
        "required": ["goal"],
    },
    is_local=True,
)


def create_orchestrate_tool(
    engine: SubEngine,
    *,
    config: OrchestratorConfig | None = None,
    depth: int = 0,
) -> ToolExecutorFn:
    """Bind `engine` + the CURRENT recursion `depth` into an orchestrate executor.

    `depth` is the recursion level of the agent that holds this tool (read
    from the execution context at wiring time, by the caller — not by this
    factory). Each nested sub-orchestration would create its own tool at
    `depth + 1`. 8B (budget-gas ceiling via Epic-F3 `GraphBudgetTracker`,
    absent from this tree) is deferred — the numeric depth guard alone
    bounds runaway recursion until F3 lands.
    """
    cfg = config or OrchestratorConfig()

    async def _execute(args: dict[str, Any]) -> str:
        if depth >= cfg.max_recursion_depth:
            return (
                f"refused: recursion depth {depth} has reached the limit "
                f"({cfg.max_recursion_depth}); not launching a "
                "sub-orchestration"
            )

        goal = args.get("goal")
        if not goal:
            return "error: 'goal' is required and must be a non-empty string"

        result = await engine.run(goal=goal, mode="dynamic", config=cfg)
        summary = f"orchestration {result.status}"
        if result.verdict is not None:
            summary += f" (gate {'passed' if result.verdict.passed else 'failed'})"
        return summary

    return _execute
