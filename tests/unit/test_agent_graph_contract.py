"""Contract tests for AgentGraph — parametrized over backends."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_types import AgentNode, EdgeType
from swarmline.multi_agent.registry_types import AgentStatus
from swarmline.protocols.agent_graph import (
    AgentGraphQuery,
    AgentGraphStore,
    AgentNodeUpdater,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def inmemory_store():
    from swarmline.multi_agent.graph_store import InMemoryAgentGraph

    return InMemoryAgentGraph()


@pytest.fixture
def sqlite_store(tmp_path):
    from swarmline.multi_agent.graph_store_sqlite import SqliteAgentGraph

    return SqliteAgentGraph(str(tmp_path / "graph.db"))


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request, inmemory_store, sqlite_store):
    if request.param == "inmemory":
        return inmemory_store
    if request.param == "sqlite":
        return sqlite_store
    raise ValueError(f"Unknown backend: {request.param}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(
    id: str = "a1",
    name: str = "Agent 1",
    role: str = "worker",
    parent_id: str | None = None,
    **kwargs,
) -> AgentNode:
    return AgentNode(id=id, name=name, role=role, parent_id=parent_id, **kwargs)


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_store_is_runtime_checkable(self, store) -> None:
        assert isinstance(store, AgentGraphStore)

    def test_query_is_runtime_checkable(self, store) -> None:
        assert isinstance(store, AgentGraphQuery)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCRUD:
    async def test_add_and_get_root(self, store) -> None:
        root = _node("ceo", "CEO", "executive")
        await store.add_node(root)
        result = await store.get_node("ceo")
        assert result is not None
        assert result.id == "ceo"
        assert result.name == "CEO"

    async def test_add_child(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech_lead", parent_id="ceo"))
        cto = await store.get_node("cto")
        assert cto is not None
        assert cto.parent_id == "ceo"

    async def test_get_missing_returns_none(self, store) -> None:
        assert await store.get_node("nope") is None

    async def test_get_children(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        await store.add_node(_node("cpo", "CPO", "product", parent_id="ceo"))
        children = await store.get_children("ceo")
        assert len(children) == 2
        ids = {c.id for c in children}
        assert ids == {"cto", "cpo"}

    async def test_get_children_empty(self, store) -> None:
        await store.add_node(_node("leaf", "Leaf", "worker"))
        children = await store.get_children("leaf")
        assert children == []

    async def test_remove_node(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        removed = await store.remove_node("ceo")
        assert removed is True
        assert await store.get_node("ceo") is None

    async def test_remove_missing_returns_false(self, store) -> None:
        assert await store.remove_node("nope") is False

    async def test_remove_cascades_to_children(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        await store.add_node(_node("eng", "Engineer", "worker", parent_id="cto"))
        await store.remove_node("cto")
        # Both CTO and engineer should be removed
        assert await store.get_node("cto") is None
        assert await store.get_node("eng") is None
        # CEO remains
        assert await store.get_node("ceo") is not None

    async def test_duplicate_id_raises(self, store) -> None:
        await store.add_node(_node("a1", "Agent 1", "worker"))
        with pytest.raises(ValueError, match="already exists"):
            await store.add_node(_node("a1", "Agent 2", "worker"))


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    async def test_parent_must_exist(self, store) -> None:
        with pytest.raises(ValueError, match="parent"):
            await store.add_node(
                _node("child", "Child", "worker", parent_id="nonexistent")
            )

    async def test_single_root_allowed(self, store) -> None:
        await store.add_node(_node("ceo1", "CEO 1", "executive"))
        # Second root is fine — tree can have forest
        await store.add_node(_node("ceo2", "CEO 2", "executive"))

    async def test_node_fields_preserved(self, store) -> None:
        node = AgentNode(
            id="rich",
            name="Rich Agent",
            role="manager",
            system_prompt="You manage things",
            parent_id=None,
            allowed_tools=("web_search", "code_sandbox"),
            skills=("research", "planning"),
            budget_limit_usd=10.0,
            status=AgentStatus.RUNNING,
            metadata={"team": "alpha"},
        )
        await store.add_node(node)
        result = await store.get_node("rich")
        assert result is not None
        assert result.system_prompt == "You manage things"
        assert result.allowed_tools == ("web_search", "code_sandbox")
        assert result.skills == ("research", "planning")
        assert result.budget_limit_usd == 10.0
        assert result.status == AgentStatus.RUNNING
        assert result.metadata["team"] == "alpha"


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


class TestTraversal:
    async def _build_org(self, store) -> None:
        """Build: CEO → CTO → [Eng1, Eng2], CEO → CPO → Designer."""
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech_lead", parent_id="ceo"))
        await store.add_node(_node("cpo", "CPO", "product", parent_id="ceo"))
        await store.add_node(_node("eng1", "Engineer 1", "engineer", parent_id="cto"))
        await store.add_node(_node("eng2", "Engineer 2", "engineer", parent_id="cto"))
        await store.add_node(_node("des", "Designer", "designer", parent_id="cpo"))

    async def test_chain_of_command(self, store) -> None:
        await self._build_org(store)
        chain = await store.get_chain_of_command("eng1")
        ids = [n.id for n in chain]
        assert ids == ["eng1", "cto", "ceo"]

    async def test_chain_of_command_root(self, store) -> None:
        await self._build_org(store)
        chain = await store.get_chain_of_command("ceo")
        assert len(chain) == 1
        assert chain[0].id == "ceo"

    async def test_subtree(self, store) -> None:
        await self._build_org(store)
        subtree = await store.get_subtree("cto")
        ids = {n.id for n in subtree}
        assert ids == {"cto", "eng1", "eng2"}

    async def test_subtree_leaf(self, store) -> None:
        await self._build_org(store)
        subtree = await store.get_subtree("eng1")
        assert len(subtree) == 1
        assert subtree[0].id == "eng1"

    async def test_subtree_full(self, store) -> None:
        await self._build_org(store)
        subtree = await store.get_subtree("ceo")
        assert len(subtree) == 6

    async def test_get_root(self, store) -> None:
        await self._build_org(store)
        root = await store.get_root()
        assert root is not None
        assert root.id == "ceo"

    async def test_get_root_empty(self, store) -> None:
        root = await store.get_root()
        assert root is None

    async def test_find_by_role(self, store) -> None:
        await self._build_org(store)
        engineers = await store.find_by_role("engineer")
        assert len(engineers) == 2
        ids = {e.id for e in engineers}
        assert ids == {"eng1", "eng2"}

    async def test_find_by_role_empty(self, store) -> None:
        await self._build_org(store)
        result = await store.find_by_role("accountant")
        assert result == []


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    async def test_snapshot_captures_all(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        snap = await store.snapshot()
        assert len(snap.nodes) == 2
        assert len(snap.edges) == 1
        assert snap.root_id == "ceo"

    async def test_snapshot_empty(self, store) -> None:
        snap = await store.snapshot()
        assert snap.nodes == ()
        assert snap.edges == ()
        assert snap.root_id is None

    async def test_snapshot_edge_type(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "executive"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        snap = await store.snapshot()
        edge = snap.edges[0]
        assert edge.source_id == "cto"
        assert edge.target_id == "ceo"
        assert edge.edge_type == EdgeType.REPORTS_TO


# ---------------------------------------------------------------------------
# Update node
# ---------------------------------------------------------------------------


class TestUpdateNode:
    def test_updater_protocol(self, store) -> None:
        assert isinstance(store, AgentNodeUpdater)

    async def test_update_name(self, store) -> None:
        await store.add_node(_node("a1", "Agent 1", "worker"))
        result = await store.update_node("a1", name="Agent One Updated")
        assert result is not None
        assert result.name == "Agent One Updated"
        assert result.id == "a1"
        # Verify persisted
        fetched = await store.get_node("a1")
        assert fetched is not None
        assert fetched.name == "Agent One Updated"

    async def test_update_role_and_prompt(self, store) -> None:
        await store.add_node(_node("a1", "Agent", "worker"))
        result = await store.update_node(
            "a1",
            role="manager",
            system_prompt="You manage things",
        )
        assert result is not None
        assert result.role == "manager"
        assert result.system_prompt == "You manage things"

    async def test_update_missing_returns_none(self, store) -> None:
        result = await store.update_node("nonexistent", name="X")
        assert result is None

    async def test_update_parent_id(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "exec"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        await store.add_node(_node("cpo", "CPO", "product", parent_id="ceo"))
        await store.add_node(_node("eng", "Engineer", "worker", parent_id="cto"))
        # Move engineer from CTO to CPO
        result = await store.update_node("eng", parent_id="cpo")
        assert result is not None
        assert result.parent_id == "cpo"
        # CTO should have no children now
        children = await store.get_children("cto")
        assert all(c.id != "eng" for c in children)
        # CPO should have engineer
        children = await store.get_children("cpo")
        assert any(c.id == "eng" for c in children)

    async def test_update_parent_nonexistent_raises(self, store) -> None:
        await store.add_node(_node("a1", "Agent", "worker"))
        with pytest.raises(ValueError, match="does not exist"):
            await store.update_node("a1", parent_id="nonexistent")

    async def test_update_parent_cycle_raises(self, store) -> None:
        await store.add_node(_node("ceo", "CEO", "exec"))
        await store.add_node(_node("cto", "CTO", "tech", parent_id="ceo"))
        await store.add_node(_node("eng", "Eng", "worker", parent_id="cto"))
        # Trying to make CEO report to its grandchild = cycle
        with pytest.raises(ValueError, match="cycle"):
            await store.update_node("ceo", parent_id="eng")

    async def test_update_preserves_unchanged_fields(self, store) -> None:
        node = AgentNode(
            id="rich",
            name="Rich",
            role="manager",
            system_prompt="Manage",
            allowed_tools=("web",),
            skills=("planning",),
            budget_limit_usd=5.0,
            status=AgentStatus.RUNNING,
            metadata={"team": "alpha"},
        )
        await store.add_node(node)
        result = await store.update_node("rich", name="Rich Updated")
        assert result is not None
        assert result.name == "Rich Updated"
        assert result.role == "manager"
        assert result.system_prompt == "Manage"
        assert result.allowed_tools == ("web",)
        assert result.budget_limit_usd == 5.0
        assert result.metadata["team"] == "alpha"
