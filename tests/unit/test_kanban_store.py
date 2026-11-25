"""Contract tests for KanbanStore + KanbanReadiness.

TDD: written before swarmline.kanban.store/inmemory/sqlite exist (must
fail on import first). ONE shared contract test parametrized over BOTH
adapters (InMemory + SQLite) per swarmline's contract-first convention —
tests must pass for ANY correct implementation of the protocol.

Covers REQ-ORC-011 (storage-agnostic Protocol, ISP <=5, InMemory+SQLite),
REQ-ORC-013 (parent-gated promotion), REQ-ORC-015 (typed block_kind +
block_recurrences + triage escalation on repeat).
"""

from __future__ import annotations

import pytest

from swarmline.kanban.store import KanbanReadiness, KanbanStore
from swarmline.kanban.types import BlockKind, KanbanStatus, KanbanTask

# ---------------------------------------------------------------------------
# Fixtures — same contract test runs against every adapter
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request: pytest.FixtureRequest):
    if request.param == "inmemory":
        from swarmline.kanban.inmemory import InMemoryKanbanStore

        return InMemoryKanbanStore()

    from swarmline.kanban.sqlite import SqliteKanbanStore

    return SqliteKanbanStore()


def _task(task_id: str, title: str = "Task", **kwargs: object) -> KanbanTask:
    return KanbanTask(id=task_id, title=title, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Protocol shape (ISP)
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_adapter_satisfies_kanban_store_protocol(self, store) -> None:
        assert isinstance(store, KanbanStore)

    def test_adapter_satisfies_kanban_readiness_protocol(self, store) -> None:
        assert isinstance(store, KanbanReadiness)

    def test_kanban_store_protocol_has_at_most_five_methods(self) -> None:
        methods = [
            name
            for name in vars(KanbanStore)
            if not name.startswith("_") and callable(getattr(KanbanStore, name))
        ]
        assert len(methods) <= 5


# ---------------------------------------------------------------------------
# create_task / list_tasks
# ---------------------------------------------------------------------------


class TestCreateAndList:
    async def test_create_task_then_list_tasks_returns_created_task(
        self, store
    ) -> None:
        await store.create_task(_task("t1", "First"))
        tasks = await store.list_tasks()
        assert [t.id for t in tasks] == ["t1"]

    async def test_list_tasks_with_status_filter_returns_only_matching(
        self, store
    ) -> None:
        await store.create_task(_task("t1", status=KanbanStatus.TODO))
        await store.create_task(_task("t2", status=KanbanStatus.DONE))
        tasks = await store.list_tasks(status=KanbanStatus.DONE)
        assert [t.id for t in tasks] == ["t2"]

    async def test_create_task_duplicate_id_rejected(self, store) -> None:
        await store.create_task(_task("t1", "First", status=KanbanStatus.TODO))

        with pytest.raises(ValueError):
            await store.create_task(_task("t1", "Second", status=KanbanStatus.DONE))

        tasks = await store.list_tasks()
        assert [t.id for t in tasks] == ["t1"]
        assert tasks[0].title == "First"
        assert tasks[0].status == KanbanStatus.TODO

    async def test_returned_task_metadata_mutation_does_not_leak_into_store(
        self, store
    ) -> None:
        await store.create_task(_task("t1", metadata={"k": "v"}))

        returned = (await store.list_tasks())[0]
        returned.metadata["k"] = "HACKED"

        refetched = (await store.list_tasks())[0]
        assert refetched.metadata["k"] == "v"


# ---------------------------------------------------------------------------
# link_tasks — multi-parent + cycle guard
# ---------------------------------------------------------------------------


class TestLinkTasks:
    async def test_link_tasks_allows_two_parents_for_one_child(self, store) -> None:
        await store.create_task(_task("parent-a"))
        await store.create_task(_task("parent-b"))
        await store.create_task(_task("child"))

        await store.link_tasks("parent-a", "child")
        await store.link_tasks("parent-b", "child")

        subtree_a = await store.get_subtree("parent-a")
        subtree_b = await store.get_subtree("parent-b")
        assert {t.id for t in subtree_a} == {"child"}
        assert {t.id for t in subtree_b} == {"child"}

    async def test_link_tasks_rejects_a_cycle(self, store) -> None:
        await store.create_task(_task("a"))
        await store.create_task(_task("b"))
        await store.link_tasks("a", "b")

        with pytest.raises(ValueError):
            await store.link_tasks("b", "a")

    async def test_link_tasks_rejects_self_link(self, store) -> None:
        await store.create_task(_task("solo"))

        with pytest.raises(ValueError):
            await store.link_tasks("solo", "solo")


# ---------------------------------------------------------------------------
# complete_task + recompute_ready — parent-gated promotion (REQ-ORC-013)
# ---------------------------------------------------------------------------


class TestParentGatedPromotion:
    async def test_completing_last_remaining_child_promotes_parent_to_ready(
        self, store
    ) -> None:
        await store.create_task(_task("parent"))
        await store.create_task(_task("child-1"))
        await store.create_task(_task("child-2"))
        await store.link_tasks("parent", "child-1")
        await store.link_tasks("parent", "child-2")

        await store.complete_task("child-1")
        await store.complete_task("child-2")
        promoted = await store.recompute_ready("parent")

        assert promoted == ["parent"]
        parents = [t for t in await store.list_tasks() if t.id == "parent"]
        assert parents[0].status == KanbanStatus.READY

    async def test_sibling_still_running_does_not_promote_parent(self, store) -> None:
        await store.create_task(_task("parent"))
        await store.create_task(_task("child-1"))
        await store.create_task(_task("child-2", status=KanbanStatus.RUNNING))
        await store.link_tasks("parent", "child-1")
        await store.link_tasks("parent", "child-2")

        await store.complete_task("child-1")
        promoted = await store.recompute_ready("parent")

        assert promoted == []
        parents = [t for t in await store.list_tasks() if t.id == "parent"]
        assert parents[0].status != KanbanStatus.READY

    async def test_completing_shared_child_promotes_both_parents(self, store) -> None:
        await store.create_task(_task("p1"))
        await store.create_task(_task("p2"))
        await store.create_task(_task("child"))
        await store.link_tasks("p1", "child")
        await store.link_tasks("p2", "child")

        await store.complete_task("child")
        promoted_p1 = await store.recompute_ready("p1")
        promoted_p2 = await store.recompute_ready("p2")

        assert promoted_p1 == ["p1"]
        assert promoted_p2 == ["p2"]
        tasks = {t.id: t for t in await store.list_tasks()}
        assert tasks["p1"].status == KanbanStatus.READY
        assert tasks["p2"].status == KanbanStatus.READY


# ---------------------------------------------------------------------------
# get_subtree
# ---------------------------------------------------------------------------


class TestGetSubtree:
    async def test_get_subtree_returns_full_recursive_child_tree(self, store) -> None:
        await store.create_task(_task("root"))
        await store.create_task(_task("mid"))
        await store.create_task(_task("leaf"))
        await store.link_tasks("root", "mid")
        await store.link_tasks("mid", "leaf")

        subtree = await store.get_subtree("root")

        assert {t.id for t in subtree} == {"mid", "leaf"}

    async def test_get_subtree_of_leaf_task_is_empty(self, store) -> None:
        await store.create_task(_task("leaf"))
        assert await store.get_subtree("leaf") == []


# ---------------------------------------------------------------------------
# set_status block transition — typed block_kind + escalation (REQ-ORC-015)
# ---------------------------------------------------------------------------


class TestBlockTransition:
    async def test_set_status_blocked_records_block_kind_and_increments_recurrences(
        self, store
    ) -> None:
        await store.create_task(_task("t1"))

        updated = await store.set_status(
            "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.NEEDS_INPUT
        )

        assert updated.status == KanbanStatus.BLOCKED
        assert updated.block_kind == BlockKind.NEEDS_INPUT
        assert updated.block_recurrences == 1

    async def test_reblocking_repeatedly_past_threshold_escalates_to_triage(
        self, store
    ) -> None:
        await store.create_task(_task("t1"))

        for _ in range(3):
            updated = await store.set_status(
                "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.DEPENDENCY
            )
            assert updated.status == KanbanStatus.BLOCKED

        escalated = await store.set_status(
            "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.DEPENDENCY
        )

        assert escalated.status == KanbanStatus.TRIAGE
        assert escalated.block_recurrences == 4

    async def test_reblock_past_threshold_still_records_block_kind(self, store) -> None:
        await store.create_task(_task("t1"))

        for _ in range(3):
            updated = await store.set_status(
                "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.CAPABILITY
            )
            assert updated.status == KanbanStatus.BLOCKED

        escalated = await store.set_status(
            "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.CAPABILITY
        )

        assert escalated.status == KanbanStatus.TRIAGE
        assert escalated.block_kind == BlockKind.CAPABILITY

    async def test_reblock_recurrences_accumulate_across_unblock(self, store) -> None:
        await store.create_task(_task("t1"))

        last_blocked = None
        for i in range(4):
            last_blocked = await store.set_status(
                "t1", KanbanStatus.BLOCKED, block_kind=BlockKind.TRANSIENT
            )
            if i < 3:
                await store.set_status("t1", KanbanStatus.RUNNING)

        # block_recurrences is cumulative and NOT reset by leaving `blocked`
        # (REQ-ORC-015): a card bouncing block<->unblock must still escalate
        # once the cumulative block count exceeds the threshold.
        assert last_blocked.status == KanbanStatus.TRIAGE
        assert last_blocked.block_recurrences == 4
