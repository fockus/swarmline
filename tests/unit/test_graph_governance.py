"""Unit: Graph governance — AgentCapabilities, GraphGovernanceConfig, enforcement."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_types import AgentCapabilities, AgentNode


# ---------------------------------------------------------------------------
# AgentCapabilities defaults
# ---------------------------------------------------------------------------


class TestAgentCapabilities:

    def test_defaults(self) -> None:
        caps = AgentCapabilities()
        assert caps.can_hire is False
        assert caps.can_delegate is True
        assert caps.max_children is None
        assert caps.can_use_subagents is False
        assert caps.allowed_subagent_ids == ()
        assert caps.can_use_team_mode is False

    def test_custom_values(self) -> None:
        caps = AgentCapabilities(
            can_hire=True,
            can_delegate=False,
            max_children=3,
            can_use_subagents=True,
            allowed_subagent_ids=("agent-1", "agent-2"),
            can_use_team_mode=True,
        )
        assert caps.can_hire is True
        assert caps.can_delegate is False
        assert caps.max_children == 3
        assert caps.can_use_subagents is True
        assert caps.allowed_subagent_ids == ("agent-1", "agent-2")
        assert caps.can_use_team_mode is True

    def test_frozen(self) -> None:
        caps = AgentCapabilities()
        with pytest.raises(AttributeError):
            caps.can_hire = True  # type: ignore[misc]

    def test_agent_node_default_capabilities(self) -> None:
        node = AgentNode(id="a1", name="Agent", role="worker")
        assert node.capabilities == AgentCapabilities()

    def test_agent_node_custom_capabilities(self) -> None:
        caps = AgentCapabilities(can_hire=True, max_children=5)
        node = AgentNode(id="a1", name="Agent", role="worker", capabilities=caps)
        assert node.capabilities.can_hire is True
        assert node.capabilities.max_children == 5


# ---------------------------------------------------------------------------
# GraphGovernanceConfig
# ---------------------------------------------------------------------------


class TestGovernanceConfig:

    def test_defaults(self) -> None:
        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig

        config = GraphGovernanceConfig()
        assert config.max_agents == 50
        assert config.max_depth == 5
        assert config.default_capabilities == AgentCapabilities()
        assert config.allow_dynamic_hiring is True
        assert config.allow_dynamic_delegation is True

    def test_custom_values(self) -> None:
        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig

        config = GraphGovernanceConfig(
            max_agents=10,
            max_depth=3,
            allow_dynamic_hiring=False,
        )
        assert config.max_agents == 10
        assert config.max_depth == 3
        assert config.allow_dynamic_hiring is False


# ---------------------------------------------------------------------------
# check_hire_allowed
# ---------------------------------------------------------------------------


class TestCheckHireAllowed:

    @pytest.fixture
    async def org(self):
        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="ceo", name="CEO", role="executive",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        await store.add_node(AgentNode(
            id="cto", name="CTO", role="tech_lead", parent_id="ceo",
            capabilities=AgentCapabilities(can_hire=True, max_children=2),
        ))
        await store.add_node(AgentNode(
            id="eng1", name="Eng1", role="engineer", parent_id="cto",
        ))
        await store.add_node(AgentNode(
            id="eng2", name="Eng2", role="engineer", parent_id="cto",
        ))
        return store

    async def test_hire_denied_no_permission(self, org) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        config = GraphGovernanceConfig()
        parent = await org.get_node("eng1")  # no can_hire
        error = await check_hire_allowed(config, parent, org)
        assert error is not None
        assert "can_hire" in error

    async def test_hire_denied_globally_disabled(self, org) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        config = GraphGovernanceConfig(allow_dynamic_hiring=False)
        parent = await org.get_node("ceo")
        error = await check_hire_allowed(config, parent, org)
        assert error is not None
        assert "globally disabled" in error.lower()

    async def test_hire_denied_max_children(self, org) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        config = GraphGovernanceConfig()
        parent = await org.get_node("cto")  # max_children=2, has 2 children
        error = await check_hire_allowed(config, parent, org)
        assert error is not None
        assert "max_children" in error

    async def test_hire_denied_max_depth(self) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="a1", name="Root", role="exec",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        await store.add_node(AgentNode(
            id="a2", name="Mid", role="mgr", parent_id="a1",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        await store.add_node(AgentNode(
            id="a3", name="Leaf", role="dev", parent_id="a2",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        config = GraphGovernanceConfig(max_depth=3)
        parent = await store.get_node("a3")  # depth 3 (a1 > a2 > a3), child would be 4
        error = await check_hire_allowed(config, parent, store)
        assert error is not None
        assert "depth" in error.lower()

    async def test_hire_denied_max_agents(self) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="a1", name="Root", role="exec",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        await store.add_node(AgentNode(
            id="a2", name="Worker", role="dev", parent_id="a1",
        ))
        config = GraphGovernanceConfig(max_agents=2)
        parent = await store.get_node("a1")
        error = await check_hire_allowed(config, parent, store)
        assert error is not None
        assert "max agents" in error.lower()

    async def test_hire_allowed(self, org) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_hire_allowed,
        )

        config = GraphGovernanceConfig()
        parent = await org.get_node("ceo")  # can_hire=True, no max_children
        error = await check_hire_allowed(config, parent, org)
        assert error is None


# ---------------------------------------------------------------------------
# check_delegate_allowed
# ---------------------------------------------------------------------------


class TestCheckDelegateAllowed:

    def test_delegate_denied_no_permission(self) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_delegate_allowed,
        )

        config = GraphGovernanceConfig()
        node = AgentNode(
            id="a1", name="Agent", role="worker",
            capabilities=AgentCapabilities(can_delegate=False),
        )
        error = check_delegate_allowed(config, node)
        assert error is not None
        assert "can_delegate" in error

    def test_delegate_denied_globally_disabled(self) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_delegate_allowed,
        )

        config = GraphGovernanceConfig(allow_dynamic_delegation=False)
        node = AgentNode(
            id="a1", name="Agent", role="worker",
            capabilities=AgentCapabilities(can_delegate=True),
        )
        error = check_delegate_allowed(config, node)
        assert error is not None
        assert "globally disabled" in error.lower()

    def test_delegate_allowed(self) -> None:
        from swarmline.multi_agent.graph_governance import (
            GraphGovernanceConfig,
            check_delegate_allowed,
        )

        config = GraphGovernanceConfig()
        node = AgentNode(
            id="a1", name="Agent", role="worker",
            capabilities=AgentCapabilities(can_delegate=True),
        )
        error = check_delegate_allowed(config, node)
        assert error is None


# ---------------------------------------------------------------------------
# GovernanceError
# ---------------------------------------------------------------------------


class TestGovernanceError:

    def test_governance_error_attrs(self) -> None:
        from swarmline.multi_agent.graph_governance import GovernanceError

        err = GovernanceError("oops", action="hire", agent_id="a1")
        assert str(err) == "oops"
        assert err.action == "hire"
        assert err.agent_id == "a1"


# ---------------------------------------------------------------------------
# Capabilities in system prompt
# ---------------------------------------------------------------------------


class TestCapabilitiesInSystemPrompt:

    async def test_capabilities_in_system_prompt(self) -> None:
        from swarmline.multi_agent.graph_context import GraphContextBuilder

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="a1", name="Agent", role="worker",
            capabilities=AgentCapabilities(
                can_hire=True, can_delegate=True, can_use_subagents=True,
            ),
        ))
        builder = GraphContextBuilder(graph_query=store)
        ctx = await builder.build_context("a1")
        prompt = builder.render_system_prompt(ctx)
        assert "## Your Permissions" in prompt
        assert "Can hire subordinates: Yes" in prompt
        assert "Can delegate tasks: Yes" in prompt
        assert "Can use subagents: Yes" in prompt

    async def test_capabilities_no_permissions_section_shows_defaults(self) -> None:
        from swarmline.multi_agent.graph_context import GraphContextBuilder

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="a1", name="Agent", role="worker",
        ))
        builder = GraphContextBuilder(graph_query=store)
        ctx = await builder.build_context("a1")
        prompt = builder.render_system_prompt(ctx)
        # Should still render permissions with default values
        assert "## Your Permissions" in prompt
        assert "Can hire subordinates: No" in prompt

    async def test_team_mode_shown_when_enabled(self) -> None:
        from swarmline.multi_agent.graph_context import GraphContextBuilder

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="a1", name="Agent", role="worker",
            capabilities=AgentCapabilities(can_use_team_mode=True),
        ))
        builder = GraphContextBuilder(graph_query=store)
        ctx = await builder.build_context("a1")
        prompt = builder.render_system_prompt(ctx)
        assert "Can use team mode: Yes" in prompt


# ---------------------------------------------------------------------------
# Builder with capabilities
# ---------------------------------------------------------------------------


class TestBuilderWithCapabilities:

    async def test_builder_add_root_with_capabilities(self) -> None:
        from swarmline.multi_agent.graph_builder import GraphBuilder

        store = InMemoryAgentGraph()
        caps = AgentCapabilities(can_hire=True, max_children=10)
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive", capabilities=caps)
        snap = await builder.build()
        assert snap.nodes[0].capabilities.can_hire is True
        assert snap.nodes[0].capabilities.max_children == 10

    async def test_builder_add_child_with_capabilities(self) -> None:
        from swarmline.multi_agent.graph_builder import GraphBuilder

        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        caps = AgentCapabilities(can_hire=False, can_delegate=False)
        builder.add_child("eng", "ceo", "Eng", "engineer", capabilities=caps)
        snap = await builder.build()
        eng = next(n for n in snap.nodes if n.id == "eng")
        assert eng.capabilities.can_hire is False
        assert eng.capabilities.can_delegate is False

    async def test_builder_default_capabilities(self) -> None:
        from swarmline.multi_agent.graph_builder import GraphBuilder

        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        snap = await builder.build()
        assert snap.nodes[0].capabilities == AgentCapabilities()

    async def test_from_dict_with_capabilities(self) -> None:
        from swarmline.multi_agent.graph_builder import GraphBuilder

        store = InMemoryAgentGraph()
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "exec",
            "capabilities": {
                "can_hire": True,
                "can_delegate": True,
                "max_children": 5,
                "can_use_subagents": True,
                "can_use_team_mode": True,
            },
            "children": [
                {
                    "id": "eng",
                    "name": "Eng",
                    "role": "engineer",
                    "capabilities": {
                        "can_hire": False,
                    },
                },
            ],
        }
        snap = await GraphBuilder.from_dict(config, store)
        ceo = snap.nodes[0]
        assert ceo.capabilities.can_hire is True
        assert ceo.capabilities.max_children == 5
        assert ceo.capabilities.can_use_team_mode is True

        eng = await store.get_node("eng")
        assert eng is not None
        assert eng.capabilities.can_hire is False
        assert eng.capabilities.can_delegate is True  # default

    async def test_from_dict_without_capabilities(self) -> None:
        from swarmline.multi_agent.graph_builder import GraphBuilder

        store = InMemoryAgentGraph()
        config = {"id": "ceo", "name": "CEO", "role": "exec"}
        snap = await GraphBuilder.from_dict(config, store)
        assert snap.nodes[0].capabilities == AgentCapabilities()


# ---------------------------------------------------------------------------
# Governance in graph tools
# ---------------------------------------------------------------------------


class TestGovernanceInGraphTools:

    @pytest.fixture
    async def org_with_caps(self):
        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="ceo", name="CEO", role="executive",
            capabilities=AgentCapabilities(can_hire=True),
        ))
        await store.add_node(AgentNode(
            id="cto", name="CTO", role="tech_lead", parent_id="ceo",
            capabilities=AgentCapabilities(can_hire=False),
        ))
        return store

    async def test_hire_blocked_by_governance(self, org_with_caps) -> None:
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(),
        )
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="New Dev", role="engineer", parent_id="cto",
        )
        assert "governance denied" in result.lower()

    async def test_hire_allowed_by_governance(self, org_with_caps) -> None:
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(),
        )
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="New Dev", role="engineer", parent_id="ceo",
        )
        assert "hired" in result.lower()

    async def test_tools_work_without_governance(self) -> None:
        """Backward compat: governance=None should not break existing behavior."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_store import InMemoryAgentGraph
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        store = InMemoryAgentGraph()
        await store.add_node(AgentNode(
            id="ceo", name="CEO", role="executive",
        ))
        tools = create_graph_tools(
            graph=store,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
        )
        hire = next(t for t in tools if t.name == "graph_hire_agent")
        result = await hire.handler(
            name="Dev", role="engineer", parent_id="ceo",
        )
        assert "hired" in result.lower()

    async def test_delegate_blocked_by_governance(self, org_with_caps) -> None:
        """delegate_task must enforce can_delegate via governance."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        # Add agent with can_delegate=False
        await org_with_caps.add_node(AgentNode(
            id="restricted", name="Restricted", role="worker", parent_id="ceo",
            capabilities=AgentCapabilities(can_delegate=False),
        ))
        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="cto", goal="Do work", caller_agent_id="restricted",
        )
        assert "governance denied" in result.lower()

    async def test_delegate_allowed_by_governance(self, org_with_caps) -> None:
        """delegate_task with can_delegate=True should succeed."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="cto", goal="Do work", caller_agent_id="ceo",
        )
        assert "delegated" in result.lower()

    async def test_delegate_globally_disabled(self, org_with_caps) -> None:
        """delegate_task denied when allow_dynamic_delegation=False."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(allow_dynamic_delegation=False),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="cto", goal="Do work", caller_agent_id="ceo",
        )
        assert "governance denied" in result.lower()

    async def test_delegate_without_caller_skips_governance(self, org_with_caps) -> None:
        """Backward compat: no caller_agent_id skips governance check."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=AsyncMock(),
            governance=GraphGovernanceConfig(),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="cto", goal="Do work",
        )
        assert "delegated" in result.lower()

    async def test_delegate_with_stage_passes_through(self, org_with_caps) -> None:
        """delegate_task with stage parameter passes it to DelegationRequest."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        orch_mock = AsyncMock()
        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=orch_mock,
            governance=GraphGovernanceConfig(),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(
            agent_id="cto", goal="Do work", stage="review",
        )
        assert "delegated" in result.lower()
        # Verify stage was passed in the DelegationRequest
        call_args = orch_mock.delegate.call_args
        req = call_args[0][0]
        assert req.stage == "review"

    async def test_delegate_without_stage_defaults_empty(self, org_with_caps) -> None:
        """delegate_task without stage defaults to empty string in DelegationRequest."""
        from unittest.mock import AsyncMock

        from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
        from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
        from swarmline.multi_agent.graph_tools import create_graph_tools

        orch_mock = AsyncMock()
        tools = create_graph_tools(
            graph=org_with_caps,
            task_board=InMemoryGraphTaskBoard(),
            orchestrator=orch_mock,
            governance=GraphGovernanceConfig(),
        )
        delegate = next(t for t in tools if t.name == "graph_delegate_task")
        result = await delegate.handler(agent_id="cto", goal="Do work")
        assert "delegated" in result.lower()
        req = orch_mock.delegate.call_args[0][0]
        assert req.stage == ""
