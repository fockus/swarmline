"""Integration: CodingTaskRuntime snapshot persistence survives restart/resume.

CTSK-03: Task state + session binding survive restart/resume.
CTSK-04: Typed snapshots roundtrip cleanly through real stores.
"""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.orchestration.coding_task_runtime import DefaultCodingTaskRuntime
from swarmline.orchestration.coding_task_types import CodingTaskStatus
from swarmline.session.task_session_store import InMemoryTaskSessionStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def board():
    return InMemoryGraphTaskBoard(namespace="coding")


@pytest.fixture
def session_store():
    return InMemoryTaskSessionStore()


def _make_runtime(board, session_store):
    return DefaultCodingTaskRuntime(board, session_store, namespace="coding")


# ---------------------------------------------------------------------------
# CTSK-03: State survives restart (new runtime instance, same stores)
# ---------------------------------------------------------------------------


class TestSnapshotSurvivesRestart:

    async def test_create_survives_restart(self, board, session_store) -> None:
        rt1 = _make_runtime(board, session_store)
        await rt1.create_task("t1", "Persistent Task", session_id="s1")

        rt2 = _make_runtime(board, session_store)
        snap = await rt2.load_snapshot("t1")
        assert snap is not None
        assert snap.task_id == "t1"
        assert snap.status == CodingTaskStatus.PENDING
        assert snap.session_id == "s1"

    async def test_active_status_survives_restart(self, board, session_store) -> None:
        rt1 = _make_runtime(board, session_store)
        await rt1.create_task("t1", "Task", session_id="s1")
        await rt1.start_task("t1", "agent-1")

        rt2 = _make_runtime(board, session_store)
        snap = await rt2.load_snapshot("t1")
        assert snap is not None
        assert snap.status == CodingTaskStatus.ACTIVE

    async def test_completed_status_survives_restart(self, board, session_store) -> None:
        rt1 = _make_runtime(board, session_store)
        await rt1.create_task("t1", "Task", session_id="s1")
        await rt1.start_task("t1", "agent-1")
        await rt1.complete_task("t1")

        rt2 = _make_runtime(board, session_store)
        snap = await rt2.load_snapshot("t1")
        assert snap is not None
        assert snap.status == CodingTaskStatus.COMPLETED

    async def test_metadata_survives_restart(self, board, session_store) -> None:
        rt1 = _make_runtime(board, session_store)
        meta = {"priority": "critical", "context": {"file": "main.py"}}
        await rt1.create_task("t1", "Task", session_id="s1", metadata=meta)

        rt2 = _make_runtime(board, session_store)
        snap = await rt2.load_snapshot("t1")
        assert snap is not None
        assert snap.metadata == meta


# ---------------------------------------------------------------------------
# CTSK-03: Session listing after restart
# ---------------------------------------------------------------------------


class TestSessionListingSurvivesRestart:

    async def test_list_snapshots_after_restart(self, board, session_store) -> None:
        rt1 = _make_runtime(board, session_store)
        for i in range(3):
            await rt1.create_task(f"t{i}", f"Task {i}", session_id="session-A")
        await rt1.create_task("t99", "Other", session_id="session-B")

        rt2 = _make_runtime(board, session_store)
        results = await rt2.list_snapshots("session-A")
        assert len(results) == 3
        assert all(s.session_id == "session-A" for s in results)


# ---------------------------------------------------------------------------
# CTSK-04: Roundtrip integrity through real stores
# ---------------------------------------------------------------------------


class TestRoundtripIntegrity:

    async def test_snapshot_dict_roundtrip_through_store(
        self, board, session_store,
    ) -> None:
        """Full path: create -> auto-persist -> load -> verify fields match."""
        rt = _make_runtime(board, session_store)
        meta = {"tools": ["read", "write"], "depth": 3}
        snap = await rt.create_task("t1", "Deep Task", session_id="s1", metadata=meta)

        loaded = await rt.load_snapshot("t1")
        assert loaded is not None
        assert loaded.task_id == snap.task_id
        assert loaded.status == snap.status
        assert loaded.session_id == snap.session_id
        assert loaded.title == snap.title
        assert loaded.metadata == snap.metadata

    async def test_multiple_transitions_snapshot_tracks(
        self, board, session_store,
    ) -> None:
        """Each transition updates the persisted snapshot."""
        rt = _make_runtime(board, session_store)
        await rt.create_task("t1", "Task", session_id="s1")

        snap1 = await rt.load_snapshot("t1")
        assert snap1 is not None
        assert snap1.status == CodingTaskStatus.PENDING

        await rt.start_task("t1", "agent-1")
        snap2 = await rt.load_snapshot("t1")
        assert snap2 is not None
        assert snap2.status == CodingTaskStatus.ACTIVE
        assert snap2.updated_at >= snap1.updated_at

        await rt.complete_task("t1")
        snap3 = await rt.load_snapshot("t1")
        assert snap3 is not None
        assert snap3.status == CodingTaskStatus.COMPLETED
        assert snap3.updated_at >= snap2.updated_at
