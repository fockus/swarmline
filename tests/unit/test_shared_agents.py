"""Tests for SharedAgentRegistry (COG-03)."""

from __future__ import annotations

from swarmline.multi_agent.graph_types import AgentNode
from swarmline.multi_agent.shared_agents import SharedAgentRegistry


def _agent(id: str, role: str = "developer", name: str = "") -> AgentNode:
    return AgentNode(id=id, name=name or id, role=role)


class TestSharedAgentRegistryBasics:
    def test_empty_registry(self) -> None:
        reg = SharedAgentRegistry()
        assert reg.get_shared_agents() == []

    def test_register_agent(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        agents = reg.get_shared_agents()
        assert len(agents) == 1
        assert agents[0].id == "j1"

    def test_register_with_explicit_shared_roles(self) -> None:
        reg = SharedAgentRegistry()
        agent = _agent("j1", "judge")
        reg.register(agent, shared_roles=("judge", "reviewer"))
        # Should be findable by both roles
        assert len(reg.get_shared_agents(role="judge")) == 1
        assert len(reg.get_shared_agents(role="reviewer")) == 1

    def test_register_uses_agent_role_if_no_shared_roles(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        assert len(reg.get_shared_agents(role="judge")) == 1

    def test_get_shared_agents_filters_by_role(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        reg.register(_agent("r1", "reviewer"))
        judges = reg.get_shared_agents(role="judge")
        assert len(judges) == 1
        assert judges[0].id == "j1"

    def test_get_shared_agents_no_filter_returns_all(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        reg.register(_agent("r1", "reviewer"))
        all_agents = reg.get_shared_agents()
        assert len(all_agents) == 2

    def test_is_shared_true(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        assert reg.is_shared("j1") is True

    def test_is_shared_false(self) -> None:
        reg = SharedAgentRegistry()
        assert reg.is_shared("nonexistent") is False

    def test_unregister(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"))
        reg.unregister("j1")
        assert reg.is_shared("j1") is False
        assert reg.get_shared_agents() == []

    def test_unregister_removes_from_roles(self) -> None:
        reg = SharedAgentRegistry()
        reg.register(_agent("j1", "judge"), shared_roles=("judge", "reviewer"))
        reg.unregister("j1")
        assert reg.get_shared_agents(role="judge") == []
        assert reg.get_shared_agents(role="reviewer") == []

    def test_unregister_nonexistent_is_noop(self) -> None:
        reg = SharedAgentRegistry()
        reg.unregister("nonexistent")  # no error
