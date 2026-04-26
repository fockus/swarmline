"""Unit: SqliteAgentRegistry — same contract as InMemory."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.agent_registry_sqlite import SqliteAgentRegistry
from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus


@pytest.fixture
def registry():
    return SqliteAgentRegistry(":memory:")


class TestCrud:
    async def test_register_and_get(self, registry) -> None:
        record = AgentRecord(id="a1", name="Agent 1", role="engineer")
        await registry.register(record)
        result = await registry.get("a1")
        assert result is not None
        assert result.name == "Agent 1"

    async def test_register_duplicate_raises(self, registry) -> None:
        record = AgentRecord(id="a1", name="Agent 1", role="engineer")
        await registry.register(record)
        with pytest.raises(ValueError, match="already registered"):
            await registry.register(record)

    async def test_get_nonexistent(self, registry) -> None:
        assert await registry.get("nope") is None


class TestList:
    async def test_list_all(self, registry) -> None:
        await registry.register(AgentRecord(id="a1", name="A1", role="eng"))
        await registry.register(AgentRecord(id="a2", name="A2", role="qa"))
        agents = await registry.list_agents()
        assert len(agents) == 2

    async def test_filter_by_role(self, registry) -> None:
        await registry.register(AgentRecord(id="a1", name="A1", role="eng"))
        await registry.register(AgentRecord(id="a2", name="A2", role="qa"))
        agents = await registry.list_agents(AgentFilter(role="eng"))
        assert len(agents) == 1
        assert agents[0].id == "a1"

    async def test_filter_by_status(self, registry) -> None:
        await registry.register(AgentRecord(id="a1", name="A1", role="eng"))
        await registry.update_status("a1", AgentStatus.RUNNING)
        agents = await registry.list_agents(AgentFilter(status=AgentStatus.RUNNING))
        assert len(agents) == 1


class TestUpdateAndRemove:
    async def test_update_status(self, registry) -> None:
        await registry.register(AgentRecord(id="a1", name="A1", role="eng"))
        ok = await registry.update_status("a1", AgentStatus.RUNNING)
        assert ok is True
        record = await registry.get("a1")
        assert record.status == AgentStatus.RUNNING

    async def test_update_nonexistent(self, registry) -> None:
        assert await registry.update_status("nope", AgentStatus.STOPPED) is False

    async def test_remove(self, registry) -> None:
        await registry.register(AgentRecord(id="a1", name="A1", role="eng"))
        ok = await registry.remove("a1")
        assert ok is True
        assert await registry.get("a1") is None

    async def test_remove_nonexistent(self, registry) -> None:
        assert await registry.remove("nope") is False
