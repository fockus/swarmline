"""Contract tests for `KanbanAssignment` — claim + heartbeat liveness (Sprint J).

TDD: written before `swarmline.kanban.store.KanbanAssignment` exists (must fail
on import first). ONE shared contract test parametrized over BOTH adapters
(InMemory + SQLite), same convention as `test_kanban_store.py`.

Mirrors hermes' `kanban_claim`/`kanban_heartbeat` semantics (kanban-unification
benchmark, AGR-007): a card records WHO is working it (`assignee`) and WHEN it
was last known alive (`claimed_at`/`last_heartbeat_at`), independent of its
lifecycle `status` — claiming/heartbeating never moves `status` on its own.
"""

from __future__ import annotations

import pytest

from swarmline.kanban.store import KanbanAssignment
from swarmline.kanban.types import KanbanTask

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
    def test_adapter_satisfies_kanban_assignment_protocol(self, store) -> None:
        assert isinstance(store, KanbanAssignment)

    def test_kanban_assignment_protocol_has_at_most_five_methods(self) -> None:
        methods = [
            name
            for name in vars(KanbanAssignment)
            if not name.startswith("_") and callable(getattr(KanbanAssignment, name))
        ]
        assert len(methods) <= 5


# ---------------------------------------------------------------------------
# claim_task
# ---------------------------------------------------------------------------


class TestClaimTask:
    async def test_claim_task_records_assignee(self, store) -> None:
        await store.create_task(_task("t1"))

        claimed = await store.claim_task("t1", assignee="claude-sonnet-4")

        assert claimed.assignee == "claude-sonnet-4"

    async def test_claim_task_stamps_claimed_at(self, store) -> None:
        await store.create_task(_task("t1"))

        claimed = await store.claim_task("t1", assignee="claude-sonnet-4")

        assert claimed.claimed_at is not None

    async def test_claim_task_stamps_initial_heartbeat(self, store) -> None:
        await store.create_task(_task("t1"))

        claimed = await store.claim_task("t1", assignee="claude-sonnet-4")

        assert claimed.last_heartbeat_at is not None

    async def test_claim_task_does_not_change_status(self, store) -> None:
        from swarmline.kanban.types import KanbanStatus

        await store.create_task(_task("t1", status=KanbanStatus.TODO))

        claimed = await store.claim_task("t1", assignee="claude-sonnet-4")

        assert claimed.status == KanbanStatus.TODO

    async def test_claim_task_unknown_id_raises(self, store) -> None:
        with pytest.raises(ValueError):
            await store.claim_task("missing", assignee="claude-sonnet-4")

    async def test_reclaiming_by_a_different_assignee_overwrites_assignee(
        self, store
    ) -> None:
        await store.create_task(_task("t1"))
        await store.claim_task("t1", assignee="agent-a")

        reclaimed = await store.claim_task("t1", assignee="agent-b")

        assert reclaimed.assignee == "agent-b"


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    async def test_heartbeat_bumps_last_heartbeat_at_forward(self, store) -> None:
        await store.create_task(_task("t1"))
        claimed = await store.claim_task("t1", assignee="claude-sonnet-4")
        first_beat = claimed.last_heartbeat_at

        beaten = await store.heartbeat("t1")

        assert beaten.last_heartbeat_at is not None
        assert beaten.last_heartbeat_at >= first_beat

    async def test_heartbeat_does_not_change_assignee(self, store) -> None:
        await store.create_task(_task("t1"))
        await store.claim_task("t1", assignee="claude-sonnet-4")

        beaten = await store.heartbeat("t1")

        assert beaten.assignee == "claude-sonnet-4"

    async def test_heartbeat_unknown_id_raises(self, store) -> None:
        with pytest.raises(ValueError):
            await store.heartbeat("missing")

    async def test_heartbeat_unclaimed_task_raises(self, store) -> None:
        await store.create_task(_task("t1"))

        with pytest.raises(ValueError):
            await store.heartbeat("t1")
