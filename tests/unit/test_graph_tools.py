"""Unit: Graph agent tools — hire, delegate, escalate."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.multi_agent.graph_orchestrator_types import DelegationRequest
from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_types import AgentNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    """CEO → CTO → [Eng1, Eng2]."""
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(
        id="ceo", name="CEO", role="executive",
        system_prompt="You are the CEO.",
    ))
    await store.add_node(AgentNode(
        id="cto", name="CTO", role="tech_lead", parent_id="ceo",
        system_prompt="You lead engineering.",
    ))
    await store.add_node(AgentNode(
        id="eng1", name="Engineer 1", role="engineer", parent_id="cto",
    ))
    await store.add_node(AgentNode(
        id="eng2", name="Engineer 2", role="engineer", parent_id="cto",
    ))
    return store


@pytest.fixture
def task_board():
    return InMemoryGraphTaskBoard()


@pytest.fixture
def orchestrator():
    return AsyncMock()


@pytest.fixture
def approval_gate():
    gate = AsyncMock()
    gate.check = AsyncMock(return_value=True)
    return gate


@pytest.fixture
def tools(org, task_board, orchestrator, approval_gate):
    """Create graph tools from factory."""
    from swarmline.multi_agent.graph_tools import create_graph_tools
    return create_graph_tools(
        graph=org,
        task_board=task_board,
        orchestrator=orchestrator,
        approval_gate=approval_gate,
    )


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


class TestToolDiscovery:

    def test_returns_three_tools(self, tools) -> None:
        assert len(tools) == 3

    def test_tool_names(self, tools) -> None:
        names = {t.name for t in tools}
        assert names == {"graph_hire_agent", "graph_delegate_task", "graph_escalate"}

    def test_all_have_tool_definition(self, tools) -> None:
        for t in tools:
            assert hasattr(t.handler, "__tool_definition__") or t.parameters


# ---------------------------------------------------------------------------
# hire_agent
# ---------------------------------------------------------------------------


class TestHireAgent:

    async def test_hire_adds_node(self, org, tools) -> None:
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="New Dev",
            role="engineer",
            parent_id="cto",
            system_prompt="You write Python.",
        )
        assert "created" in result.lower() or "hired" in result.lower()

        # Node should exist in graph
        children = await org.get_children("cto")
        names = [c.name for c in children]
        assert "New Dev" in names

    async def test_hire_requires_approval(self, tools, approval_gate) -> None:
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        await hire.handler(
            name="Temp Dev", role="engineer", parent_id="cto",
        )
        approval_gate.check.assert_called()

    async def test_hire_denied(self, org, tools, approval_gate) -> None:
        approval_gate.check = AsyncMock(return_value=False)
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="Denied Dev", role="engineer", parent_id="cto",
        )
        assert "denied" in result.lower()

        # Node should NOT exist
        children = await org.get_children("cto")
        names = [c.name for c in children]
        assert "Denied Dev" not in names

    async def test_hire_with_tools_and_config(self, org, tools) -> None:
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        await hire.handler(
            name="ML Dev",
            role="ml_engineer",
            parent_id="cto",
            system_prompt="You train models.",
            allowed_tools="code_sandbox,gpu_cluster",
        )
        children = await org.get_children("cto")
        ml_dev = next(c for c in children if c.name == "ML Dev")
        assert "code_sandbox" in ml_dev.allowed_tools
        assert "gpu_cluster" in ml_dev.allowed_tools

    async def test_hire_invalid_parent_raises(self, tools) -> None:
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="Orphan", role="engineer", parent_id="nonexistent",
        )
        assert "error" in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# delegate_task
# ---------------------------------------------------------------------------


class TestDelegateTask:

    async def test_delegate_calls_orchestrator(self, tools, orchestrator) -> None:
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        await delegate.handler(
            agent_id="eng1",
            goal="Implement login",
            parent_task_id="root-task",
        )
        orchestrator.delegate.assert_called_once()
        call_args = orchestrator.delegate.call_args[0][0]
        assert isinstance(call_args, DelegationRequest)
        assert call_args.task_id.startswith("task-")  # server-generated
        assert call_args.agent_id == "eng1"

    async def test_delegate_returns_confirmation(self, tools) -> None:
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="eng1", goal="Build API",
        )
        assert "delegated" in result.lower()

    async def test_delegate_invalid_agent(self, tools) -> None:
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="nonexistent", goal="Build",
        )
        assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------


class TestEscalate:

    async def test_escalate_sends_message(self, tools) -> None:
        escalate = next(t for t in tools if t.name == "graph_escalate")
        result = await escalate.handler(
            from_agent_id="eng1",
            message="Blocked on API key",
            task_id="t-1",
        )
        assert "escalated" in result.lower()

    async def test_escalate_invalid_agent(self, tools) -> None:
        escalate = next(t for t in tools if t.name == "graph_escalate")
        result = await escalate.handler(
            from_agent_id="nonexistent",
            message="Help",
        )
        assert "not found" in result.lower() or "error" in result.lower()
