"""Contract tests for GraphCommunication — direct, broadcast, escalation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage
from swarmline.multi_agent.graph_communication import InMemoryGraphCommunication
from swarmline.multi_agent.graph_store import InMemoryAgentGraph
from swarmline.multi_agent.graph_types import AgentNode
from swarmline.protocols.graph_comm import GraphCommunication


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    """Build: CEO → CTO → [Eng1, Eng2], CEO → CPO."""
    store = InMemoryAgentGraph()
    await store.add_node(AgentNode(id="ceo", name="CEO", role="executive"))
    await store.add_node(AgentNode(id="cto", name="CTO", role="tech", parent_id="ceo"))
    await store.add_node(
        AgentNode(id="cpo", name="CPO", role="product", parent_id="ceo")
    )
    await store.add_node(
        AgentNode(id="eng1", name="Eng1", role="engineer", parent_id="cto")
    )
    await store.add_node(
        AgentNode(id="eng2", name="Eng2", role="engineer", parent_id="cto")
    )
    return store


@pytest.fixture
def comm(org):
    return InMemoryGraphCommunication(graph_query=org)


@pytest.fixture
def comm_with_bus(org):
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return InMemoryGraphCommunication(graph_query=org, event_bus=bus), bus


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_implements_protocol(self, comm) -> None:
        assert isinstance(comm, GraphCommunication)


# ---------------------------------------------------------------------------
# Direct messaging
# ---------------------------------------------------------------------------


class TestDirect:
    async def test_send_direct(self, comm) -> None:
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        inbox = await comm.get_inbox("cto")
        assert len(inbox) == 1
        assert inbox[0].content == "hi"

    async def test_direct_not_in_other_inbox(self, comm) -> None:
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        assert await comm.get_inbox("cpo") == []

    async def test_inbox_empty_by_default(self, comm) -> None:
        assert await comm.get_inbox("eng1") == []


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    async def test_broadcast_reaches_descendants(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Update for all engineers")
        eng1_inbox = await comm.get_inbox("eng1")
        eng2_inbox = await comm.get_inbox("eng2")
        assert len(eng1_inbox) == 1
        assert len(eng2_inbox) == 1
        assert eng1_inbox[0].channel == ChannelType.BROADCAST

    async def test_broadcast_skips_sender(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Update")
        cto_inbox = await comm.get_inbox("cto")
        assert cto_inbox == []

    async def test_broadcast_does_not_reach_other_branches(self, comm) -> None:
        await comm.broadcast_subtree("cto", "Tech update")
        cpo_inbox = await comm.get_inbox("cpo")
        assert cpo_inbox == []

    async def test_broadcast_from_root(self, comm) -> None:
        await comm.broadcast_subtree("ceo", "Company-wide announcement")
        assert len(await comm.get_inbox("cto")) == 1
        assert len(await comm.get_inbox("cpo")) == 1
        assert len(await comm.get_inbox("eng1")) == 1
        assert len(await comm.get_inbox("eng2")) == 1


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


class TestEscalation:
    async def test_escalate_reaches_ancestors(self, comm) -> None:
        await comm.escalate("eng1", "Blocked on API key")
        cto_inbox = await comm.get_inbox("cto")
        ceo_inbox = await comm.get_inbox("ceo")
        assert len(cto_inbox) == 1
        assert len(ceo_inbox) == 1
        assert cto_inbox[0].channel == ChannelType.ESCALATION

    async def test_escalate_skips_self(self, comm) -> None:
        await comm.escalate("eng1", "Help")
        eng1_inbox = await comm.get_inbox("eng1")
        assert eng1_inbox == []

    async def test_escalate_does_not_reach_siblings(self, comm) -> None:
        await comm.escalate("eng1", "Help")
        eng2_inbox = await comm.get_inbox("eng2")
        assert eng2_inbox == []


# ---------------------------------------------------------------------------
# Thread by task_id
# ---------------------------------------------------------------------------


class TestThread:
    async def test_thread_filters_by_task(self, comm) -> None:
        msg1 = GraphMessage(
            id="m1",
            from_agent_id="ceo",
            to_agent_id="cto",
            content="About task T1",
            task_id="T1",
        )
        msg2 = GraphMessage(
            id="m2",
            from_agent_id="cto",
            to_agent_id="eng1",
            content="About task T2",
            task_id="T2",
        )
        await comm.send_direct(msg1)
        await comm.send_direct(msg2)
        thread = await comm.get_thread("T1")
        assert len(thread) == 1
        assert thread[0].task_id == "T1"

    async def test_thread_empty(self, comm) -> None:
        assert await comm.get_thread("nonexistent") == []


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------


class TestEventBus:
    async def test_direct_emits_event(self, comm_with_bus) -> None:
        comm, bus = comm_with_bus
        msg = GraphMessage(
            id="m1", from_agent_id="ceo", to_agent_id="cto", content="hi"
        )
        await comm.send_direct(msg)
        bus.emit.assert_called_once()
        call_args = bus.emit.call_args
        assert call_args[0][0] == "graph.message.direct"

    async def test_broadcast_emits_per_recipient(self, comm_with_bus) -> None:
        comm, bus = comm_with_bus
        await comm.broadcast_subtree("cto", "Update")
        assert bus.emit.call_count == 2  # eng1 + eng2

    async def test_escalate_emits_per_ancestor(self, comm_with_bus) -> None:
        comm, bus = comm_with_bus
        await comm.escalate("eng1", "Help")
        assert bus.emit.call_count == 2  # cto + ceo
