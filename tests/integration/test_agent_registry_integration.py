"""Integration tests for InMemoryAgentRegistry.

Tests real multi-step workflows: full lifecycle, parent-child hierarchy,
and protocol conformance.
"""

from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry
from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from swarmline.protocols.multi_agent import AgentRegistry
import pytest

pytestmark = pytest.mark.integration


def _record(
    id: str = "a1",
    name: str = "Agent",
    role: str = "coder",
    **kwargs,
) -> AgentRecord:
    return AgentRecord(id=id, name=name, role=role, **kwargs)


class TestAgentRegistryIntegration:
    async def test_agent_registry_full_lifecycle_register_update_remove(self):
        """Full CRUD lifecycle: register -> get -> update_status -> list -> remove -> get returns None."""
        # Arrange
        registry = InMemoryAgentRegistry()
        record = _record(id="agent-1", name="Worker", role="coder")

        # Act: register
        await registry.register(record)

        # Assert: get returns registered record
        got = await registry.get("agent-1")
        assert got == record
        assert got.status == AgentStatus.IDLE

        # Act: update status to RUNNING
        ok = await registry.update_status("agent-1", AgentStatus.RUNNING)
        assert ok is True

        # Assert: status updated
        got = await registry.get("agent-1")
        assert got is not None
        assert got.status == AgentStatus.RUNNING

        # Assert: list returns the agent
        agents = await registry.list_agents()
        assert len(agents) == 1
        assert agents[0].id == "agent-1"

        # Act: remove
        removed = await registry.remove("agent-1")
        assert removed is True

        # Assert: get returns None after removal
        got = await registry.get("agent-1")
        assert got is None

    async def test_agent_registry_tree_hierarchy_parent_child_filter(self):
        """Parent + 2 children: filter by parent_id returns only children, not parent."""
        # Arrange
        registry = InMemoryAgentRegistry()
        parent = _record(id="lead-1", name="Lead", role="lead")
        child_a = _record(
            id="worker-1",
            name="Worker A",
            role="coder",
            parent_id="lead-1",
        )
        child_b = _record(
            id="worker-2",
            name="Worker B",
            role="reviewer",
            parent_id="lead-1",
        )

        # Act: register parent and children
        await registry.register(parent)
        await registry.register(child_a)
        await registry.register(child_b)

        # Assert: filter by parent_id returns only children
        children = await registry.list_agents(AgentFilter(parent_id="lead-1"))
        assert len(children) == 2
        child_ids = {r.id for r in children}
        assert child_ids == {"worker-1", "worker-2"}

        # Assert: parent is NOT in the filtered result
        assert all(r.id != "lead-1" for r in children)

        # Assert: unfiltered list returns all 3
        all_agents = await registry.list_agents()
        assert len(all_agents) == 3

    async def test_agent_registry_protocol_isinstance_check_passes(self):
        """InMemoryAgentRegistry satisfies the AgentRegistry protocol at runtime."""
        # Arrange
        registry = InMemoryAgentRegistry()

        # Assert
        assert isinstance(registry, AgentRegistry)
