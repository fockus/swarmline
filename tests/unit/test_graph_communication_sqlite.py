"""Unit: SqliteGraphCommunication — same contract as InMemory."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage
from swarmline.multi_agent.graph_communication_sqlite import SqliteGraphCommunication
from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_types import AgentNode


@pytest.fixture
async def org():
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(id="ceo", name="CEO", role="executive"))
    await store.add_node(AgentNode(id="cto", name="CTO", role="tech", parent_id="ceo"))
    await store.add_node(
        AgentNode(id="eng1", name="Eng1", role="engineer", parent_id="cto")
    )
    await store.add_node(
        AgentNode(id="eng2", name="Eng2", role="engineer", parent_id="cto")
    )
    return store


@pytest.fixture
def comm(org):
    return SqliteGraphCommunication(graph_query=org)


class TestDirect:
    async def test_send_and_inbox(self, comm) -> None:
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        inbox = await comm.get_inbox("cto")
        assert len(inbox) == 1
        assert inbox[0].content == "hi"

    async def test_not_in_other_inbox(self, comm) -> None:
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        assert await comm.get_inbox("eng1") == []


class TestBroadcast:
    async def test_reaches_descendants(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Update")
        assert len(await comm.get_inbox("eng1")) == 1
        assert len(await comm.get_inbox("eng2")) == 1

    async def test_skips_sender(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Update")
        assert await comm.get_inbox("cto") == []

    async def test_does_not_reach_other_branches(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Tech update")
        assert await comm.get_inbox("ceo") == []


class TestEscalation:
    async def test_reaches_ancestors(self, comm) -> None:
        await comm.escalate("eng1", "Blocked")
        cto_inbox = await comm.get_inbox("cto")
        ceo_inbox = await comm.get_inbox("ceo")
        assert len(cto_inbox) == 1
        assert len(ceo_inbox) == 1
        assert cto_inbox[0].channel == ChannelType.ESCALATION

    async def test_skips_self(self, comm) -> None:
        await comm.escalate("eng1", "Help")
        assert await comm.get_inbox("eng1") == []


class TestThread:
    async def test_filter_by_task(self, comm) -> None:
        m1 = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="T1", task_id="T1"
        )
        m2 = GraphMessage(
            id="m2", from_agent_id="cto", to_agent_id="eng1", content="T2", task_id="T2"
        )
        await comm.send_direct(m1)
        await comm.send_direct(m2)
        thread = await comm.get_thread("T1")
        assert len(thread) == 1
        assert thread[0].task_id == "T1"


class TestEventBus:
    async def test_direct_emits(self, org) -> None:
        bus = AsyncMock()
        bus.emit = AsyncMock()
        comm = SqliteGraphCommunication(graph_query=org, event_bus=bus)
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        bus.emit.assert_called_once()
        assert bus.emit.call_args[0][0] == "graph.message.direct"
