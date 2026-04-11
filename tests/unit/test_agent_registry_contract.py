"""Contract tests for AgentRegistry protocol.

Fixture-based: any correct AgentRegistry implementation must pass all tests.
"""

import pytest

from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus


@pytest.fixture(params=["inmemory"])
def registry(request):
    from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry

    if request.param == "inmemory":
        return InMemoryAgentRegistry()


def _record(
    id: str = "a1",
    name: str = "Agent",
    role: str = "coder",
    **kwargs,
) -> AgentRecord:
    return AgentRecord(id=id, name=name, role=role, **kwargs)


class TestAgentRegistryContract:
    async def test_register_and_get_returns_same_record(self, registry):
        record = _record()
        await registry.register(record)
        result = await registry.get("a1")
        assert result == record

    async def test_get_nonexistent_returns_none(self, registry):
        result = await registry.get("nonexistent")
        assert result is None

    async def test_register_duplicate_raises_value_error(self, registry):
        await registry.register(_record())
        with pytest.raises(ValueError, match="already registered"):
            await registry.register(_record())

    async def test_list_all_agents(self, registry):
        for i in range(3):
            await registry.register(_record(id=f"a{i}", name=f"Agent{i}"))
        result = await registry.list_agents()
        assert len(result) == 3

    async def test_list_with_role_filter(self, registry):
        await registry.register(_record(id="a1", role="coder"))
        await registry.register(_record(id="a2", role="reviewer"))
        await registry.register(_record(id="a3", role="coder"))

        result = await registry.list_agents(AgentFilter(role="coder"))
        assert len(result) == 2
        assert all(r.role == "coder" for r in result)

    async def test_list_by_parent_id(self, registry):
        await registry.register(_record(id="parent", role="lead"))
        await registry.register(
            _record(id="child1", role="coder", parent_id="parent"),
        )
        await registry.register(
            _record(id="child2", role="reviewer", parent_id="parent"),
        )

        children = await registry.list_agents(AgentFilter(parent_id="parent"))
        assert len(children) == 2
        assert {r.id for r in children} == {"child1", "child2"}

    async def test_list_with_status_filter(self, registry):
        await registry.register(_record(id="a1"))
        await registry.register(_record(id="a2"))
        await registry.update_status("a1", AgentStatus.RUNNING)

        result = await registry.list_agents(AgentFilter(status=AgentStatus.RUNNING))
        assert len(result) == 1
        assert result[0].id == "a1"

    async def test_update_status_idle_to_running(self, registry):
        await registry.register(_record())
        ok = await registry.update_status("a1", AgentStatus.RUNNING)
        assert ok is True
        updated = await registry.get("a1")
        assert updated is not None
        assert updated.status == AgentStatus.RUNNING

    async def test_update_nonexistent_returns_false(self, registry):
        ok = await registry.update_status("ghost", AgentStatus.STOPPED)
        assert ok is False

    async def test_remove_agent(self, registry):
        await registry.register(_record())
        ok = await registry.remove("a1")
        assert ok is True
        assert await registry.get("a1") is None

    async def test_remove_nonexistent_returns_false(self, registry):
        ok = await registry.remove("ghost")
        assert ok is False
