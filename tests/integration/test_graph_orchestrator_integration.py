"""Integration: 7-agent graph orchestration with real components.

Graph:
  CEO (executive)
    ├── CTO (tech_lead)
    │   ├── Backend Lead (backend_lead)
    │   │   ├── BE-Dev1 (engineer)
    │   │   └── BE-Dev2 (engineer)
    │   └── Frontend Lead (frontend_lead)
    │       └── FE-Dev1 (engineer)
    └── CPO (product_owner)

Scenario: CEO starts goal → CTO and CPO each get tasks →
CTO delegates to leads → leads delegate to devs →
results bubble up → all tasks complete.
"""

from __future__ import annotations

import asyncio

import pytest

from swarmline.multi_agent.graph_communication import InMemoryGraphCommunication
from swarmline.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
from swarmline.multi_agent.graph_orchestrator_types import (
    DelegationRequest,
    OrchestratorRunState,
)
from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_types import AgentNode
from swarmline.observability.event_bus import InMemoryEventBus

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def seven_agent_org():
    """Build a 7-agent organization graph."""
    store = InMemoryAgentGraph()
    await store.add_node(
        AgentNode(
            id="ceo",
            name="CEO",
            role="executive",
            system_prompt="You decompose company goals into tech and product streams.",
            allowed_tools=("web_search",),
        )
    )
    await store.add_node(
        AgentNode(
            id="cto",
            name="CTO",
            role="tech_lead",
            parent_id="ceo",
            system_prompt="You lead engineering. Delegate to backend and frontend leads.",
            allowed_tools=("code_sandbox",),
        )
    )
    await store.add_node(
        AgentNode(
            id="cpo",
            name="CPO",
            role="product_owner",
            parent_id="ceo",
            system_prompt="You handle product requirements and user stories.",
        )
    )
    await store.add_node(
        AgentNode(
            id="be-lead",
            name="Backend Lead",
            role="backend_lead",
            parent_id="cto",
            system_prompt="You lead the backend team.",
            allowed_tools=("database",),
        )
    )
    await store.add_node(
        AgentNode(
            id="fe-lead",
            name="Frontend Lead",
            role="frontend_lead",
            parent_id="cto",
            system_prompt="You lead the frontend team.",
        )
    )
    await store.add_node(
        AgentNode(
            id="be-dev1",
            name="BE-Dev1",
            role="engineer",
            parent_id="be-lead",
        )
    )
    await store.add_node(
        AgentNode(
            id="be-dev2",
            name="BE-Dev2",
            role="engineer",
            parent_id="be-lead",
        )
    )
    return store


@pytest.fixture
def task_board():
    return InMemoryGraphTaskBoard()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSevenAgentOrchestration:
    """Full integration: 7 agents, 3 levels of delegation, parallel execution."""

    async def test_three_level_delegation(
        self, seven_agent_org, task_board, event_bus
    ) -> None:
        """CEO → CTO/CPO → leads → devs: all tasks complete."""
        # Track which agents were called
        called_agents: list[str] = []

        async def mock_runner(
            agent_id: str, task_id: str, goal: str, system_prompt: str
        ) -> str:
            called_agents.append(agent_id)
            await asyncio.sleep(0.02)  # simulate work
            return f"{agent_id} completed: {goal}"

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=mock_runner,
            event_bus=event_bus,
            max_concurrent=5,
        )

        # Level 0: CEO starts
        run_id = await orch.start("Build a SaaS platform")
        status = await orch.get_status(run_id)
        root_task = status.root_task_id

        # Level 1: CEO delegates to CTO and CPO (parallel)
        await orch.delegate(
            DelegationRequest(
                task_id="task-cto",
                agent_id="cto",
                goal="Design technical architecture",
                parent_task_id=root_task,
            )
        )
        await orch.delegate(
            DelegationRequest(
                task_id="task-cpo",
                agent_id="cpo",
                goal="Write user stories",
                parent_task_id=root_task,
            )
        )
        await asyncio.sleep(0.1)

        # Level 2: CTO delegates to leads
        await orch.delegate(
            DelegationRequest(
                task_id="task-be-lead",
                agent_id="be-lead",
                goal="Design API layer",
                parent_task_id="task-cto",
            )
        )
        await orch.delegate(
            DelegationRequest(
                task_id="task-fe-lead",
                agent_id="fe-lead",
                goal="Design UI components",
                parent_task_id="task-cto",
            )
        )
        await asyncio.sleep(0.1)

        # Level 3: Backend Lead delegates to devs
        await orch.delegate(
            DelegationRequest(
                task_id="task-be-dev1",
                agent_id="be-dev1",
                goal="Implement user API",
                parent_task_id="task-be-lead",
            )
        )
        await orch.delegate(
            DelegationRequest(
                task_id="task-be-dev2",
                agent_id="be-dev2",
                goal="Implement payment API",
                parent_task_id="task-be-lead",
            )
        )
        await asyncio.sleep(0.2)

        # Verify all agents ran
        assert "cto" in called_agents
        assert "cpo" in called_agents
        assert "be-lead" in called_agents
        assert "fe-lead" in called_agents
        assert "be-dev1" in called_agents
        assert "be-dev2" in called_agents

        # Verify results
        assert await orch.collect_result("task-cto") is not None
        assert await orch.collect_result("task-cpo") is not None
        assert await orch.collect_result("task-be-dev1") is not None
        assert await orch.collect_result("task-be-dev2") is not None

    async def test_parallel_execution_bounded(
        self, seven_agent_org, task_board, event_bus
    ) -> None:
        """Concurrent tasks don't exceed max_concurrent."""
        concurrent_count = 0
        max_seen = 0

        async def counting_runner(agent_id, task_id, goal, system_prompt):
            nonlocal concurrent_count, max_seen
            concurrent_count += 1
            if concurrent_count > max_seen:
                max_seen = concurrent_count
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return "done"

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=counting_runner,
            event_bus=event_bus,
            max_concurrent=2,  # strict limit
        )

        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        # Fire 4 tasks simultaneously
        for i in range(4):
            await orch.delegate(
                DelegationRequest(
                    task_id=f"t-{i}",
                    agent_id="be-dev1",
                    goal=f"Task {i}",
                    parent_task_id=status.root_task_id,
                )
            )
        await asyncio.sleep(0.5)

        assert max_seen <= 2

    async def test_failure_with_escalation(
        self, seven_agent_org, task_board, event_bus
    ) -> None:
        """Agent failure triggers escalation event."""
        comm = InMemoryGraphCommunication(
            graph_query=seven_agent_org, event_bus=event_bus
        )
        delegate_call_count = 0

        async def failing_runner(agent_id, task_id, goal, system_prompt):
            nonlocal delegate_call_count
            if agent_id == "be-dev1":
                delegate_call_count += 1
            raise RuntimeError("DB connection failed")

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=failing_runner,
            event_bus=event_bus,
            communication=comm,
            max_retries=1,
        )

        run_id = await orch.start("Build")
        await asyncio.sleep(0.2)  # Let root agent execution settle
        status = await orch.get_status(run_id)

        await orch.delegate(
            DelegationRequest(
                task_id="fail-task",
                agent_id="be-dev1",
                goal="Connect to DB",
                parent_task_id=status.root_task_id,
                max_retries=1,
            )
        )
        await asyncio.sleep(1.0)  # backoff: 0.5s before retry

        # Should have retried once (2 attempts total) for the delegated agent
        assert delegate_call_count == 2

        # Escalation message should reach ancestors (be-lead, cto, ceo)
        be_lead_inbox = await comm.get_inbox("be-lead")
        cto_inbox = await comm.get_inbox("cto")
        assert len(be_lead_inbox) >= 1
        assert len(cto_inbox) >= 1

    async def test_context_propagation(self, seven_agent_org, task_board) -> None:
        """Agent receives context-aware system prompt with chain of command."""
        received_prompts: dict[str, str] = {}

        async def prompt_capturing_runner(agent_id, task_id, goal, system_prompt):
            received_prompts[agent_id] = system_prompt
            return "done"

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=prompt_capturing_runner,
            max_concurrent=5,
        )

        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        await orch.delegate(
            DelegationRequest(
                task_id="ctx-task",
                agent_id="be-dev1",
                goal="Implement API",
                parent_task_id=status.root_task_id,
            )
        )
        await asyncio.sleep(0.1)

        prompt = received_prompts.get("be-dev1", "")
        # Should contain chain of command
        assert "CEO" in prompt
        assert "CTO" in prompt
        assert "Backend Lead" in prompt
        assert "BE-Dev1" in prompt
        # Should contain inherited tools
        assert (
            "web_search" in prompt or "code_sandbox" in prompt or "database" in prompt
        )

    async def test_event_lifecycle(
        self, seven_agent_org, task_board, event_bus
    ) -> None:
        """EventBus receives full lifecycle: started → delegated → completed."""
        events: list[str] = []
        event_bus.subscribe("graph.orchestrator.*", lambda data: None)

        # Capture events via a listener
        original_emit = event_bus.emit

        async def capturing_emit(topic: str, data: dict) -> None:
            events.append(topic)
            await original_emit(topic, data)

        event_bus.emit = capturing_emit  # type: ignore[method-assign]

        async def quick_runner(agent_id, task_id, goal, system_prompt):
            return "done"

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=quick_runner,
            event_bus=event_bus,
        )

        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        await orch.delegate(
            DelegationRequest(
                task_id="evt-task",
                agent_id="cto",
                goal="Design",
                parent_task_id=status.root_task_id,
            )
        )
        await asyncio.sleep(0.1)
        await orch.stop(run_id)

        assert "graph.orchestrator.started" in events
        assert "graph.orchestrator.delegated" in events
        assert "graph.orchestrator.agent_completed" in events
        assert "graph.orchestrator.stopped" in events

    async def test_stop_during_execution(
        self, seven_agent_org, task_board, event_bus
    ) -> None:
        """Stop cancels pending background tasks."""
        started = asyncio.Event()

        async def slow_runner(agent_id, task_id, goal, system_prompt):
            started.set()
            await asyncio.sleep(10)  # very long
            return "should not complete"

        orch = DefaultGraphOrchestrator(
            graph=seven_agent_org,
            task_board=task_board,
            agent_runner=slow_runner,
            event_bus=event_bus,
        )

        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        await orch.delegate(
            DelegationRequest(
                task_id="slow-task",
                agent_id="be-dev1",
                goal="Long work",
                parent_task_id=status.root_task_id,
            )
        )
        await started.wait()
        await orch.stop(run_id)

        final_status = await orch.get_status(run_id)
        assert final_status.state == OrchestratorRunState.STOPPED
