"""Unit: supervisor handoff helper drives the EXISTING graph runtime (REQ-003).

H6 supervisor-orchestrator, Task 5. ADR (design.md — "handoffs = существующие
графы, не переизобретать"): `handoff()` is a THIN wrapper that builds a
`DelegationRequest` and drives the REAL `DefaultGraphOrchestrator.delegate` +
`.wait_for_task` — no new handoff primitive/type. Fixture shape mirrors
`tests/unit/test_graph_orchestrator.py::TestDelegate::test_delegate_creates_subtask`
(InMemoryAgentGraph + InMemoryGraphTaskBoard + a plain agent_runner callable)
to prove reuse, not reinvention.
"""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_types import AgentNode
from swarmline.orchestration.supervisor.handoff import GraphHandoffRunner, handoff


async def _agent_runner(
    agent_id: str, task_id: str, goal: str, system_prompt: str
) -> str:
    return f"handled:{agent_id}:{goal}"


@pytest.fixture
async def graph() -> InMemoryAgentGraph:
    """root (lead) → worker (engineer) — minimal 2-node graph."""
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(id="root", name="Root", role="lead"))
    await store.add_node(
        AgentNode(id="worker", name="Worker", role="engineer", parent_id="root")
    )
    return store


@pytest.fixture
def task_board() -> InMemoryGraphTaskBoard:
    return InMemoryGraphTaskBoard()


@pytest.fixture
def orchestrator(
    graph: InMemoryAgentGraph, task_board: InMemoryGraphTaskBoard
) -> DefaultGraphOrchestrator:
    return DefaultGraphOrchestrator(
        graph=graph, task_board=task_board, agent_runner=_agent_runner
    )


class TestHandoffUsesExistingGraphRuntime:
    @pytest.mark.asyncio
    async def test_handoff_uses_existing_graph_runtime(
        self,
        orchestrator: DefaultGraphOrchestrator,
        task_board: InMemoryGraphTaskBoard,
    ) -> None:
        """A subtask is created on the REAL task board and the worker's
        result round-trips back through `wait_for_task` — proving `handoff()`
        drives the existing graph runtime, not a parallel mechanism."""
        run_id = await orchestrator.start("root goal")
        status = await orchestrator.get_status(run_id)

        result = await handoff(
            orchestrator,
            agent_id="worker",
            goal="do the subtask",
            parent_task_id=status.root_task_id,
            task_id="handoff-1",
        )

        subtasks = await task_board.get_subtasks(status.root_task_id)
        assert any(t.id == "handoff-1" for t in subtasks)
        assert result == "handled:worker:do the subtask"

    @pytest.mark.asyncio
    async def test_default_graph_orchestrator_satisfies_graph_handoff_runner(
        self, orchestrator: DefaultGraphOrchestrator
    ) -> None:
        """`DefaultGraphOrchestrator` structurally satisfies the narrow
        2-method `GraphHandoffRunner` Protocol `handoff()` depends on —
        proof the helper targets the real orchestrator's actual surface."""
        assert isinstance(orchestrator, GraphHandoffRunner)

    @pytest.mark.asyncio
    async def test_handoff_generates_a_task_id_when_omitted(
        self, orchestrator: DefaultGraphOrchestrator
    ) -> None:
        run_id = await orchestrator.start("root goal")
        status = await orchestrator.get_status(run_id)

        result = await handoff(
            orchestrator,
            agent_id="worker",
            goal="task without an explicit id",
            parent_task_id=status.root_task_id,
        )

        assert result == "handled:worker:task without an explicit id"

    @pytest.mark.asyncio
    async def test_handoff_returns_none_on_timeout(
        self, orchestrator: DefaultGraphOrchestrator
    ) -> None:
        """`timeout` is forwarded verbatim to `wait_for_task` (no bespoke
        timeout/cancellation logic reinvented in the helper)."""

        async def _slow_runner(
            agent_id: str, task_id: str, goal: str, system_prompt: str
        ) -> str:
            import asyncio

            await asyncio.sleep(10)
            return "too late"

        slow_orchestrator = DefaultGraphOrchestrator(
            graph=orchestrator._graph,
            task_board=orchestrator._task_board,
            agent_runner=_slow_runner,
        )
        run_id = await slow_orchestrator.start("root goal")
        status = await slow_orchestrator.get_status(run_id)

        result = await handoff(
            slow_orchestrator,
            agent_id="worker",
            goal="never finishes in time",
            parent_task_id=status.root_task_id,
            task_id="handoff-timeout",
            timeout=0.01,
        )

        assert result is None
