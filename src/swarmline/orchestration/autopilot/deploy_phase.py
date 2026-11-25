"""Deploy phase — materialize graph + seed board + execute via handoff.

Epic G, Task 5A. Covers REQ-013 (materialize the blueprint's `graph` dict
into a real `GraphSnapshot` via the EXISTING `GraphBuilder.from_dict`, and
seed an `InMemoryGraphTaskBoard` with one `GraphTaskItem` per `BlueprintTask`)
and REQ-014 (execute each task through the H6 `handoff()` seam — no parallel
execution loop is reinvented here; `handoff()` already owns retries via the
delegated `DelegationRequest.max_retries`).

REQ-015 (per-node routing to a *distinct* runtime/provider adapter, declared
on the graph node) is Epic-F4-gated: `multi_agent/agent_adapter.py` and an
`AdapterRegistry` do not exist yet in this tree. Until F4 lands, ALL nodes
execute through the single injected `orchestrator` (a `GraphHandoffRunner`)
— there is no per-node dispatch to fake here, so `DeployPhase` does not
attempt it.

Kept import-light on purpose (mirrors `orchestration/supervisor/handoff.py`,
I-020): `swarmline.multi_agent.*` eagerly pulls `runtime.thin` the moment
`swarmline/multi_agent/__init__.py` runs, so `GraphBuilder`,
`InMemoryAgentGraph`, `InMemoryGraphTaskBoard`, and `GraphTaskItem` are
imported LAZILY, inside `deploy()`, never at module level.

Supervisor-opt-in boundary: the H6 `handoff()` seam lives in
`orchestration/supervisor/`, an OPT-IN package. autopilot is a sanctioned
level-C consumer of it (ADR-G, "layered over the closed H6 supervisor"), so
`handoff` is imported LAZILY inside `deploy()` — never at module scope and
never on the `GraphHandoffRunner` type annotation (TYPE_CHECKING only) — so
merely importing `swarmline.orchestration.autopilot` does NOT pull the
supervisor package. Mirrors `harness/agent_assembly.py`'s sanctioned-lazy
pattern; see `tests/unit/test_supervisor_opt_in.py` (allowed set + import-light
proof).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from swarmline.orchestration.autopilot.types import (
    BlueprintTask,
    OrchestrationBlueprint,
)

if TYPE_CHECKING:
    from swarmline.multi_agent.graph_task_types import GraphTaskItem
    from swarmline.multi_agent.graph_types import GraphSnapshot
    from swarmline.orchestration.supervisor.handoff import GraphHandoffRunner

__all__ = ["DeployPhase", "DeployResult"]


@dataclass(frozen=True)
class DeployResult:
    """Outcome of a `DeployPhase.deploy` call."""

    snapshot: GraphSnapshot  # materialized graph
    artifacts: dict[str, str]  # task_id -> handoff result string
    board_snapshot: tuple[GraphTaskItem, ...]  # seeded tasks, for observability


class DeployPhase:
    """Materialize a blueprint's graph, seed its task board, execute it.

    Reuses (never re-implements):
      - `GraphBuilder.from_dict` (multi_agent/graph_builder.py) to turn the
        blueprint's nested-dict `graph` into a real `GraphSnapshot`.
      - `InMemoryGraphTaskBoard` (multi_agent/graph_task_board.py) to seed
        one `GraphTaskItem` per `BlueprintTask`.
      - `handoff()` (orchestration/supervisor/handoff.py, H6 seam) to drive
        each task's execution against the injected `orchestrator`.
    """

    def __init__(self, orchestrator: GraphHandoffRunner, *, board: Any = None) -> None:
        self._orchestrator = orchestrator
        self._board = board

    async def deploy(self, blueprint: OrchestrationBlueprint) -> DeployResult:
        """Materialize `blueprint.graph`, seed the board, execute every task.

        Tasks execute sequentially in blueprint order via `handoff()` — the
        orchestrator owns retries/timeouts, this method does not add its own
        retry/parallelism loop on top.
        """
        from swarmline.multi_agent.graph_builder import GraphBuilder
        from swarmline.multi_agent.graph_store import InMemoryAgentGraph
        from swarmline.orchestration.supervisor.handoff import handoff

        snapshot = await GraphBuilder.from_dict(blueprint.graph, InMemoryAgentGraph())

        board = self._board
        if board is None:
            from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard

            board = InMemoryGraphTaskBoard()

        for task in blueprint.tasks:
            await board.create_task(self._to_task_item(task))

        artifacts: dict[str, str] = {}
        for task in blueprint.tasks:
            result = await handoff(
                self._orchestrator,
                agent_id=task.assignee_node_id,
                goal=task.goal,
                task_id=task.id,
            )
            if result is not None:
                artifacts[task.id] = result

        board_snapshot = tuple(await board.list_tasks())
        return DeployResult(
            snapshot=snapshot, artifacts=artifacts, board_snapshot=board_snapshot
        )

    @staticmethod
    def _to_task_item(task: BlueprintTask) -> Any:
        from swarmline.multi_agent.graph_task_types import GraphTaskItem

        return GraphTaskItem(
            id=task.id,
            title=task.title,
            description=task.goal,
            assignee_agent_id=task.assignee_node_id,
            dependencies=task.depends_on,
        )
