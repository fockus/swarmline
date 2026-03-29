"""Unit: DefaultGraphOrchestrator — mocked runtime, task board, communication."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from cognitia.multi_agent.graph_orchestrator_types import (
    DelegationRequest,
    OrchestratorRunState,
)
from cognitia.multi_agent.graph_store import InMemoryAgentGraph
from cognitia.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from cognitia.multi_agent.graph_types import AgentNode
from cognitia.protocols.graph_orchestrator import GraphOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_runner(results: dict[str, str] | None = None, fail_ids: set[str] | None = None):
    """Create a mock agent_runner callable.

    agent_runner(agent_id, task_id, goal, system_prompt) -> str
    """
    results = results or {}
    fail_ids = fail_ids or set()

    async def runner(agent_id: str, task_id: str, goal: str, system_prompt: str) -> str:
        if agent_id in fail_ids:
            raise RuntimeError(f"Agent {agent_id} failed")
        return results.get(agent_id, f"Result from {agent_id}")

    return runner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    """CEO → CTO → [Eng1, Eng2]."""
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(
        id="ceo", name="CEO", role="executive",
        system_prompt="You are the CEO. Decompose goals into tasks for your reports.",
    ))
    await store.add_node(AgentNode(
        id="cto", name="CTO", role="tech_lead",
        parent_id="ceo",
        system_prompt="You lead engineering.",
    ))
    await store.add_node(AgentNode(
        id="eng1", name="Engineer 1", role="engineer",
        parent_id="cto",
    ))
    await store.add_node(AgentNode(
        id="eng2", name="Engineer 2", role="engineer",
        parent_id="cto",
    ))
    return store


@pytest.fixture
def task_board():
    return InMemoryGraphTaskBoard()


@pytest.fixture
def event_bus():
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def make_orchestrator(org, task_board, event_bus):
    """Factory to create orchestrator with custom runner."""
    def _make(agent_runner=None, max_concurrent=5, max_retries=2, approval_gate=None):
        # Lazy import — implementation doesn't exist yet during TDD red phase
        from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
        return DefaultGraphOrchestrator(
            graph=org,
            task_board=task_board,
            agent_runner=agent_runner or _make_agent_runner(),
            event_bus=event_bus,
            max_concurrent=max_concurrent,
            max_retries=max_retries,
            approval_gate=approval_gate,
        )
    return _make


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocol:

    def test_implements_protocol(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        assert isinstance(orch, GraphOrchestrator)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


class TestStart:

    async def test_start_returns_run_id(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build a web app")
        assert isinstance(run_id, str)
        assert len(run_id) > 0

    async def test_start_creates_root_task(self, make_orchestrator, task_board) -> None:
        orch = make_orchestrator()
        await orch.start("Build a web app")
        tasks = await task_board.list_tasks()
        assert len(tasks) >= 1
        assert tasks[0].title == "Build a web app"

    async def test_start_assigns_root_agent(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build a web app")
        status = await orch.get_status(run_id)
        assert status.root_agent_id is not None

    async def test_start_emits_event(self, make_orchestrator, event_bus) -> None:
        orch = make_orchestrator()
        await orch.start("Build a web app")
        calls = [c[0] for c in event_bus.emit.call_args_list]
        started = [c for c in calls if c[0] == "graph.orchestrator.started"]
        assert len(started) == 1
        assert started[0][1]["goal"] == "Build a web app"
        assert "run_id" in started[0][1]


# ---------------------------------------------------------------------------
# Delegate
# ---------------------------------------------------------------------------


class TestDelegate:

    async def test_delegate_creates_subtask(self, make_orchestrator, task_board) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build a web app")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1",
            agent_id="cto",
            goal="Design architecture",
            parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        subtasks = await task_board.get_subtasks(status.root_task_id)
        assert any(t.id == "sub-1" for t in subtasks)

    async def test_delegate_runs_agent(self, make_orchestrator) -> None:
        runner = AsyncMock(return_value="Done designing")
        orch = make_orchestrator(agent_runner=runner)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="cto",
            goal="Design", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        # Wait for async execution
        await asyncio.sleep(0.1)
        runner.assert_called()

    async def test_delegate_emits_event(self, make_orchestrator, event_bus) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code it", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.1)
        # Should have emitted delegation event
        calls = [c[0][0] for c in event_bus.emit.call_args_list]
        assert "graph.orchestrator.delegated" in calls


# ---------------------------------------------------------------------------
# Collect result
# ---------------------------------------------------------------------------


class TestCollectResult:

    async def test_collect_after_completion(self, make_orchestrator) -> None:
        runner = AsyncMock(return_value="API designed")
        orch = make_orchestrator(agent_runner=runner)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="cto",
            goal="Design API", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.1)

        result = await orch.collect_result("sub-1")
        assert result == "API designed"

    async def test_collect_pending_returns_none(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        result = await orch.collect_result("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Get status
# ---------------------------------------------------------------------------


class TestGetStatus:

    async def test_status_after_start(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)
        assert status.run_id == run_id
        assert status.state == OrchestratorRunState.RUNNING

    async def test_status_tracks_executions(self, make_orchestrator) -> None:
        runner = AsyncMock(return_value="Done")
        orch = make_orchestrator(agent_runner=runner)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.1)

        status = await orch.get_status(run_id)
        assert status.completed_count >= 1

    async def test_status_unknown_run_raises(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        with pytest.raises(KeyError):
            await orch.get_status("nonexistent-run")


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestStop:

    async def test_stop_sets_stopped_state(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build")
        await orch.stop(run_id)
        status = await orch.get_status(run_id)
        assert status.state == OrchestratorRunState.STOPPED

    async def test_stop_emits_event(self, make_orchestrator, event_bus) -> None:
        orch = make_orchestrator()
        run_id = await orch.start("Build")
        await orch.stop(run_id)
        calls = [c[0][0] for c in event_bus.emit.call_args_list]
        assert "graph.orchestrator.stopped" in calls

    async def test_stop_unknown_run_raises(self, make_orchestrator) -> None:
        orch = make_orchestrator()
        with pytest.raises(KeyError):
            await orch.stop("nonexistent-run")


# ---------------------------------------------------------------------------
# Failure & retry
# ---------------------------------------------------------------------------


class TestFailureHandling:

    async def test_retry_on_failure(self, make_orchestrator) -> None:
        """Agent fails first, succeeds on retry."""
        task_calls: dict[str, int] = {}

        async def flaky_runner(agent_id, task_id, goal, system_prompt):
            task_calls[task_id] = task_calls.get(task_id, 0) + 1
            if task_calls[task_id] == 1:
                raise RuntimeError("Transient error")
            return "Recovered"

        orch = make_orchestrator(agent_runner=flaky_runner, max_retries=2)
        run_id = await orch.start("Build")
        await asyncio.sleep(0.1)  # Let root agent execution settle
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.2)

        result = await orch.collect_result("sub-1")
        assert result == "Recovered"
        assert task_calls["sub-1"] == 2

    async def test_escalate_after_max_retries(self, make_orchestrator, event_bus) -> None:
        """After exhausting retries, escalation event is emitted."""
        async def always_fail(agent_id, task_id, goal, system_prompt):
            raise RuntimeError("Permanent error")

        orch = make_orchestrator(agent_runner=always_fail, max_retries=1)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code", parent_task_id=status.root_task_id,
            max_retries=1,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.3)

        calls = [c[0][0] for c in event_bus.emit.call_args_list]
        assert "graph.orchestrator.escalated" in calls


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:

    async def test_parallel_delegation(self, make_orchestrator) -> None:
        """Multiple delegations run in parallel, bounded by semaphore."""
        execution_order: list[str] = []

        async def slow_runner(agent_id, task_id, goal, system_prompt):
            execution_order.append(f"start:{agent_id}")
            await asyncio.sleep(0.05)
            execution_order.append(f"end:{agent_id}")
            return f"Done by {agent_id}"

        orch = make_orchestrator(agent_runner=slow_runner, max_concurrent=5)
        run_id = await orch.start("Build")
        await asyncio.sleep(0.1)  # Let root agent execution settle
        status = await orch.get_status(run_id)

        reqs = [
            DelegationRequest(task_id=f"sub-{i}", agent_id=f"eng{i % 2 + 1}",
                              goal=f"Task {i}", parent_task_id=status.root_task_id)
            for i in range(3)
        ]
        for req in reqs:
            await orch.delegate(req)
        await asyncio.sleep(0.3)

        # Root + 3 delegated = 4 total starts (root now auto-launches)
        delegate_starts = [e for e in execution_order if e.startswith("start:eng")]
        assert len(delegate_starts) == 3


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


class TestApprovalGate:

    async def test_delegate_with_approval(self, make_orchestrator) -> None:
        """Delegation proceeds when approval gate approves."""
        gate = AsyncMock()
        gate.check = AsyncMock(return_value=True)

        orch = make_orchestrator(approval_gate=gate)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.1)

        gate.check.assert_called()
        result = await orch.collect_result("sub-1")
        assert result is not None

    async def test_delegate_denied_by_gate(self, make_orchestrator, event_bus) -> None:
        """Delegation is rejected when approval gate denies."""
        gate = AsyncMock()
        gate.check = AsyncMock(return_value=False)

        orch = make_orchestrator(approval_gate=gate)
        run_id = await orch.start("Build")
        status = await orch.get_status(run_id)

        req = DelegationRequest(
            task_id="sub-1", agent_id="eng1",
            goal="Code", parent_task_id=status.root_task_id,
        )
        await orch.delegate(req)
        await asyncio.sleep(0.1)

        # Task should not have run
        result = await orch.collect_result("sub-1")
        assert result is None
        calls = [c[0][0] for c in event_bus.emit.call_args_list]
        assert "graph.orchestrator.denied" in calls


# ---------------------------------------------------------------------------
# Context-aware runner (dual dispatch)
# ---------------------------------------------------------------------------


class TestContextAwareRunner:

    async def test_context_aware_runner_receives_execution_context(
        self, make_orchestrator,
    ) -> None:
        """Orchestrator with 1-arg runner passes AgentExecutionContext."""
        from cognitia.multi_agent.graph_execution_context import AgentExecutionContext

        received: list[AgentExecutionContext] = []

        async def ctx_runner(ctx: AgentExecutionContext) -> str:
            received.append(ctx)
            return f"Done by {ctx.agent_id}"

        orch = make_orchestrator(agent_runner=ctx_runner)
        await orch.start("Build a web app")
        await asyncio.sleep(0.15)

        assert len(received) >= 1
        ctx = received[0]
        assert isinstance(ctx, AgentExecutionContext)
        assert ctx.goal == "Build a web app"
        assert ctx.agent_id is not None
        assert ctx.system_prompt is not None

    async def test_legacy_runner_still_works(self, make_orchestrator) -> None:
        """Orchestrator with 4-arg runner continues to work (backward compat)."""
        calls: list[tuple[str, str, str, str]] = []

        async def legacy_runner(agent_id: str, task_id: str, goal: str, system_prompt: str) -> str:
            calls.append((agent_id, task_id, goal, system_prompt))
            return f"Legacy result from {agent_id}"

        orch = make_orchestrator(agent_runner=legacy_runner)
        await orch.start("Build")
        await asyncio.sleep(0.15)

        assert len(calls) >= 1
        agent_id, task_id, goal, system_prompt = calls[0]
        assert isinstance(agent_id, str)
        assert isinstance(system_prompt, str)
        assert goal == "Build"

    async def test_context_has_tools_and_skills(self, org, task_board, event_bus) -> None:
        """AgentExecutionContext includes tools and skills from AgentNode."""
        from cognitia.multi_agent.graph_execution_context import AgentExecutionContext
        from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
        from cognitia.multi_agent.graph_types import AgentNode

        # Create a graph with tools and skills on the root node
        from cognitia.multi_agent.graph_store import InMemoryAgentGraph

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="root",
            name="Root",
            role="root",
            system_prompt="You are root.",
            allowed_tools=("search", "code_exec"),
            skills=("python", "sql"),
        ))

        received: list[AgentExecutionContext] = []

        async def ctx_runner(ctx: AgentExecutionContext) -> str:
            received.append(ctx)
            return "ok"

        orch = DefaultGraphOrchestrator(
            graph=store,
            task_board=task_board,
            agent_runner=ctx_runner,
            event_bus=event_bus,
        )
        await orch.start("Do something")
        await asyncio.sleep(0.15)

        assert len(received) >= 1
        ctx = received[0]
        assert "search" in ctx.tools
        assert "code_exec" in ctx.tools
        assert "python" in ctx.skills
        assert "sql" in ctx.skills
