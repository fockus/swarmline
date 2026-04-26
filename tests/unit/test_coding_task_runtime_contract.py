"""Contract tests for CodingTaskRuntime — lifecycle, snapshots, readiness, resume.

RED phase: all tests expected to fail (NotImplementedError) until GREEN implementation.

Requirements covered:
    CTSK-01: Task lifecycle backed by GraphTaskBoard
    CTSK-02: todo_read/todo_write provider-backed (allow-list expansion)
    CTSK-03: Task state + session binding survive restart/resume
    CTSK-04: Typed snapshots roundtrip cleanly
    CTSK-05: Missing provider/binding fails fast
"""

from __future__ import annotations

import time

import pytest

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.orchestration.coding_task_ports import (
    CodingTaskLifecyclePort,
    CodingTaskReadinessPort,
    CodingTaskResumePort,
)
from swarmline.orchestration.coding_task_runtime import DefaultCodingTaskRuntime
from swarmline.orchestration.coding_task_types import (
    CodingTaskSnapshot,
    CodingTaskStatus,
    _CODING_TO_TASK,
    _TASK_TO_CODING,
)
from swarmline.runtime.thin.coding_toolpack import CODING_TOOL_NAMES
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


@pytest.fixture
def runtime(board, session_store):
    return DefaultCodingTaskRuntime(board, session_store, namespace="coding")


# ---------------------------------------------------------------------------
# Domain types — CodingTaskStatus
# ---------------------------------------------------------------------------


class TestCodingTaskStatus:
    def test_all_statuses_defined(self) -> None:
        expected = {"pending", "active", "completed", "blocked", "cancelled"}
        actual = {s.value for s in CodingTaskStatus}
        assert actual == expected

    @pytest.mark.parametrize(
        ("coding", "task"),
        [
            ("pending", "todo"),
            ("active", "in_progress"),
            ("completed", "done"),
            ("blocked", "blocked"),
            ("cancelled", "cancelled"),
        ],
    )
    def test_status_mapping_coding_to_task(self, coding: str, task: str) -> None:
        assert _CODING_TO_TASK[coding] == task

    @pytest.mark.parametrize(
        ("task", "coding"),
        [
            ("todo", "pending"),
            ("in_progress", "active"),
            ("done", "completed"),
            ("blocked", "blocked"),
            ("cancelled", "cancelled"),
        ],
    )
    def test_status_mapping_task_to_coding(self, task: str, coding: str) -> None:
        assert _TASK_TO_CODING[task] == coding

    def test_mapping_bijectivity(self) -> None:
        """Every CodingTaskStatus maps to a unique TaskStatus and back."""
        assert len(_CODING_TO_TASK) == len(CodingTaskStatus)
        assert len(_TASK_TO_CODING) == len(CodingTaskStatus)
        for coding_val, task_val in _CODING_TO_TASK.items():
            assert _TASK_TO_CODING[task_val] == coding_val


# ---------------------------------------------------------------------------
# Domain types — CodingTaskSnapshot (CTSK-04)
# ---------------------------------------------------------------------------


class TestCodingTaskSnapshot:
    def test_frozen(self) -> None:
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.PENDING,
            session_id="s1",
            title="Test",
        )
        with pytest.raises(AttributeError):
            snap.task_id = "t2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        before = time.time()
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.PENDING,
            session_id="s1",
            title="Test",
        )
        after = time.time()
        assert before <= snap.created_at <= after
        assert before <= snap.updated_at <= after
        assert snap.metadata == {}

    def test_to_dict_keys(self) -> None:
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.ACTIVE,
            session_id="s1",
            title="Task",
            created_at=1000.0,
            updated_at=2000.0,
            metadata={"key": "val"},
        )
        d = snap.to_dict()
        expected_keys = {
            "task_id",
            "status",
            "session_id",
            "title",
            "created_at",
            "updated_at",
            "metadata",
        }
        assert set(d.keys()) == expected_keys
        assert d["status"] == "active"
        assert d["metadata"] == {"key": "val"}

    def test_roundtrip_to_dict_from_dict(self) -> None:
        """CTSK-04: Typed snapshots roundtrip cleanly."""
        original = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.COMPLETED,
            session_id="s1",
            title="Roundtrip",
            created_at=1000.0,
            updated_at=2000.0,
            metadata={"nested": {"key": "value"}, "count": 42},
        )
        rebuilt = CodingTaskSnapshot.from_dict(original.to_dict())
        assert rebuilt.task_id == original.task_id
        assert rebuilt.status == original.status
        assert rebuilt.session_id == original.session_id
        assert rebuilt.title == original.title
        assert rebuilt.created_at == original.created_at
        assert rebuilt.updated_at == original.updated_at
        assert rebuilt.metadata == original.metadata

    @pytest.mark.parametrize("status", list(CodingTaskStatus))
    def test_roundtrip_all_statuses(self, status: CodingTaskStatus) -> None:
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=status,
            session_id="s1",
            title="T",
            created_at=100.0,
            updated_at=200.0,
        )
        rebuilt = CodingTaskSnapshot.from_dict(snap.to_dict())
        assert rebuilt.status == status

    def test_from_dict_missing_metadata_defaults(self) -> None:
        data = {
            "task_id": "t1",
            "status": "pending",
            "session_id": "s1",
            "title": "T",
            "created_at": 100.0,
            "updated_at": 200.0,
        }
        snap = CodingTaskSnapshot.from_dict(data)
        assert snap.metadata == {}

    def test_from_dict_invalid_status_raises(self) -> None:
        data = {
            "task_id": "t1",
            "status": "invalid_status",
            "session_id": "s1",
            "title": "T",
            "created_at": 100.0,
            "updated_at": 200.0,
        }
        with pytest.raises(ValueError):
            CodingTaskSnapshot.from_dict(data)


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_lifecycle_port(self, runtime) -> None:
        assert isinstance(runtime, CodingTaskLifecyclePort)

    def test_readiness_port(self, runtime) -> None:
        assert isinstance(runtime, CodingTaskReadinessPort)

    def test_resume_port(self, runtime) -> None:
        assert isinstance(runtime, CodingTaskResumePort)


# ---------------------------------------------------------------------------
# CTSK-05: Missing provider / binding fails fast
# ---------------------------------------------------------------------------


class TestMissingProviderFailFast:
    def test_none_board_raises(self, session_store) -> None:
        with pytest.raises(ValueError, match="board is required"):
            DefaultCodingTaskRuntime(None, session_store)  # type: ignore[arg-type]

    def test_none_session_store_raises(self, board) -> None:
        with pytest.raises(ValueError, match="session_store is required"):
            DefaultCodingTaskRuntime(board, None)  # type: ignore[arg-type]

    def test_valid_construction(self, board, session_store) -> None:
        rt = DefaultCodingTaskRuntime(board, session_store)
        assert rt is not None


# ---------------------------------------------------------------------------
# CTSK-01: Task lifecycle backed by GraphTaskBoard
# ---------------------------------------------------------------------------


class TestLifecycleCreate:
    async def test_create_task_returns_pending_snapshot(self, runtime) -> None:
        snap = await runtime.create_task("t1", "My Task", session_id="s1")
        assert isinstance(snap, CodingTaskSnapshot)
        assert snap.task_id == "t1"
        assert snap.title == "My Task"
        assert snap.status == CodingTaskStatus.PENDING
        assert snap.session_id == "s1"

    async def test_create_task_with_metadata(self, runtime) -> None:
        meta = {"priority": "high", "tags": ["urgent"]}
        snap = await runtime.create_task("t1", "Task", session_id="s1", metadata=meta)
        assert snap.metadata == meta

    async def test_create_task_default_session_id(self, runtime) -> None:
        snap = await runtime.create_task("t1", "Task")
        assert snap.session_id == ""

    async def test_create_task_persists_to_board(self, runtime, board) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        tasks = await board.list_tasks()
        assert any(t.id == "t1" for t in tasks)


class TestLifecycleStart:
    async def test_start_task_returns_active_snapshot(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        snap = await runtime.start_task("t1", "agent-1")
        assert snap.status == CodingTaskStatus.ACTIVE
        assert snap.task_id == "t1"

    async def test_start_task_nonexistent_raises_lookup(self, runtime) -> None:
        with pytest.raises(LookupError):
            await runtime.start_task("nonexistent", "agent-1")

    async def test_start_task_already_active_raises_value(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        with pytest.raises((ValueError, LookupError)):
            await runtime.start_task("t1", "agent-2")

    async def test_start_task_completed_raises_value(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        await runtime.complete_task("t1")
        with pytest.raises((ValueError, LookupError)):
            await runtime.start_task("t1", "agent-2")


class TestLifecycleComplete:
    async def test_complete_task_returns_completed_snapshot(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        snap = await runtime.complete_task("t1")
        assert snap.status == CodingTaskStatus.COMPLETED
        assert snap.task_id == "t1"

    async def test_complete_task_without_start_raises(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        with pytest.raises(ValueError):
            await runtime.complete_task("t1")

    async def test_complete_task_nonexistent_raises(self, runtime) -> None:
        with pytest.raises(LookupError):
            await runtime.complete_task("nonexistent")

    async def test_complete_already_completed_raises(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        await runtime.complete_task("t1")
        with pytest.raises((ValueError, LookupError)):
            await runtime.complete_task("t1")


class TestLifecycleCancel:
    async def test_cancel_pending_returns_true(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        result = await runtime.cancel_task("t1")
        assert result is True

    async def test_cancel_active_returns_true(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        result = await runtime.cancel_task("t1")
        assert result is True

    async def test_cancel_completed_returns_false(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        await runtime.complete_task("t1")
        result = await runtime.cancel_task("t1")
        assert result is False

    async def test_cancel_nonexistent_returns_false(self, runtime) -> None:
        result = await runtime.cancel_task("nonexistent")
        assert result is False


class TestLifecycleGetStatus:
    async def test_status_after_create(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.PENDING

    async def test_status_after_start(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.ACTIVE

    async def test_status_after_complete(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        await runtime.complete_task("t1")
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.COMPLETED

    async def test_status_after_cancel(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.cancel_task("t1")
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.CANCELLED

    async def test_status_nonexistent_returns_none(self, runtime) -> None:
        status = await runtime.get_status("nonexistent")
        assert status is None


class TestLifecycleFullPath:
    async def test_create_start_complete(self, runtime) -> None:
        """Full happy path: create -> start -> complete."""
        s1 = await runtime.create_task("t1", "Task", session_id="s1")
        assert s1.status == CodingTaskStatus.PENDING

        s2 = await runtime.start_task("t1", "agent-1")
        assert s2.status == CodingTaskStatus.ACTIVE

        s3 = await runtime.complete_task("t1")
        assert s3.status == CodingTaskStatus.COMPLETED

    async def test_create_start_cancel(self, runtime) -> None:
        """Alternate path: create -> start -> cancel."""
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")
        result = await runtime.cancel_task("t1")
        assert result is True
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.CANCELLED

    async def test_create_cancel(self, runtime) -> None:
        """Direct cancel from pending."""
        await runtime.create_task("t1", "Task", session_id="s1")
        result = await runtime.cancel_task("t1")
        assert result is True
        status = await runtime.get_status("t1")
        assert status == CodingTaskStatus.CANCELLED


# ---------------------------------------------------------------------------
# Invalid transition matrix
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    @pytest.mark.parametrize(
        ("setup_status", "action", "action_kwargs"),
        [
            # Cannot complete a PENDING task (must start first)
            ("pending", "complete_task", {"task_id": "t1"}),
            # Cannot start a COMPLETED task
            ("completed", "start_task", {"task_id": "t1", "agent_id": "a"}),
            # Cannot complete a COMPLETED task again
            ("completed", "complete_task", {"task_id": "t1"}),
            # Cannot start a CANCELLED task
            ("cancelled", "start_task", {"task_id": "t1", "agent_id": "a"}),
        ],
        ids=[
            "complete-pending",
            "start-completed",
            "complete-completed",
            "start-cancelled",
        ],
    )
    async def test_invalid_transition_raises(
        self,
        runtime,
        setup_status: str,
        action: str,
        action_kwargs: dict,
    ) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        if setup_status in ("completed", "cancelled"):
            await runtime.start_task("t1", "agent-1")
        if setup_status == "completed":
            await runtime.complete_task("t1")
        elif setup_status == "cancelled":
            await runtime.cancel_task("t1")

        with pytest.raises((ValueError, LookupError)):
            await getattr(runtime, action)(**action_kwargs)


# ---------------------------------------------------------------------------
# CTSK-01: Readiness
# ---------------------------------------------------------------------------


class TestReadiness:
    async def test_is_ready_no_deps(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        assert await runtime.is_ready("t1") is True

    async def test_get_blockers_no_deps_empty(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        blockers = await runtime.get_blockers("t1")
        assert blockers == []

    async def test_list_by_status_pending(self, runtime) -> None:
        await runtime.create_task("t1", "Task A", session_id="s1")
        await runtime.create_task("t2", "Task B", session_id="s1")
        await runtime.create_task("t3", "Task C", session_id="s1")
        await runtime.start_task("t3", "agent-1")

        pending = await runtime.list_by_status(CodingTaskStatus.PENDING)
        pending_ids = {s.task_id for s in pending}
        assert "t1" in pending_ids
        assert "t2" in pending_ids
        assert "t3" not in pending_ids

    async def test_list_by_status_active(self, runtime) -> None:
        await runtime.create_task("t1", "Task", session_id="s1")
        await runtime.start_task("t1", "agent-1")

        active = await runtime.list_by_status(CodingTaskStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].task_id == "t1"
        assert active[0].status == CodingTaskStatus.ACTIVE


# ---------------------------------------------------------------------------
# CTSK-03 + CTSK-04: Snapshot resume
# ---------------------------------------------------------------------------


class TestSnapshotResume:
    async def test_save_and_load_snapshot(self, runtime) -> None:
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.ACTIVE,
            session_id="s1",
            title="Test",
            created_at=1000.0,
            updated_at=2000.0,
            metadata={"key": "val"},
        )
        await runtime.save_snapshot(snap)
        loaded = await runtime.load_snapshot("t1")
        assert loaded is not None
        assert loaded.task_id == "t1"
        assert loaded.status == CodingTaskStatus.ACTIVE
        assert loaded.session_id == "s1"
        assert loaded.metadata == {"key": "val"}

    async def test_load_snapshot_missing_returns_none(self, runtime) -> None:
        result = await runtime.load_snapshot("nonexistent")
        assert result is None

    async def test_list_snapshots_by_session(self, runtime) -> None:
        for i in range(3):
            snap = CodingTaskSnapshot(
                task_id=f"t{i}",
                status=CodingTaskStatus.PENDING,
                session_id="s1",
                title=f"Task {i}",
                created_at=1000.0,
                updated_at=2000.0,
            )
            await runtime.save_snapshot(snap)
        other = CodingTaskSnapshot(
            task_id="t99",
            status=CodingTaskStatus.PENDING,
            session_id="other-session",
            title="Other",
            created_at=1000.0,
            updated_at=2000.0,
        )
        await runtime.save_snapshot(other)

        results = await runtime.list_snapshots("s1")
        assert len(results) == 3
        assert all(s.session_id == "s1" for s in results)

    async def test_delete_snapshot_existing_returns_true(self, runtime) -> None:
        snap = CodingTaskSnapshot(
            task_id="t1",
            status=CodingTaskStatus.PENDING,
            session_id="s1",
            title="Task",
            created_at=1000.0,
            updated_at=2000.0,
        )
        await runtime.save_snapshot(snap)
        result = await runtime.delete_snapshot("t1")
        assert result is True
        assert await runtime.load_snapshot("t1") is None

    async def test_delete_snapshot_missing_returns_false(self, runtime) -> None:
        result = await runtime.delete_snapshot("nonexistent")
        assert result is False

    async def test_lifecycle_auto_persists_snapshot(self, runtime) -> None:
        """CTSK-03: Status transitions auto-persist snapshots."""
        await runtime.create_task("t1", "Task", session_id="s1")
        snap_pending = await runtime.load_snapshot("t1")
        assert snap_pending is not None
        assert snap_pending.status == CodingTaskStatus.PENDING

        await runtime.start_task("t1", "agent-1")
        snap_active = await runtime.load_snapshot("t1")
        assert snap_active is not None
        assert snap_active.status == CodingTaskStatus.ACTIVE

        await runtime.complete_task("t1")
        snap_completed = await runtime.load_snapshot("t1")
        assert snap_completed is not None
        assert snap_completed.status == CodingTaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# CTSK-02: Allow-list expansion — todo_read / todo_write in coding tools
# ---------------------------------------------------------------------------


class TestAllowListExpansion:
    def test_coding_tool_names_includes_todo_read(self) -> None:
        assert "todo_read" in CODING_TOOL_NAMES

    def test_coding_tool_names_includes_todo_write(self) -> None:
        assert "todo_write" in CODING_TOOL_NAMES

    def test_coding_tool_names_total_count(self) -> None:
        """After expansion: 8 sandbox + 2 todo = 10 tools."""
        assert len(CODING_TOOL_NAMES) == 10

    def test_original_sandbox_tools_preserved(self) -> None:
        """Expansion must not drop any existing tools."""
        original_eight = {
            "read",
            "write",
            "edit",
            "multi_edit",
            "bash",
            "ls",
            "glob",
            "grep",
        }
        assert original_eight.issubset(CODING_TOOL_NAMES)


# ---------------------------------------------------------------------------
# Edge cases: task_id validation and list_by_status fallback
# ---------------------------------------------------------------------------


class TestTaskIdValidation:
    """create_task validates task_id content."""

    @pytest.mark.parametrize("bad_id", ["", "  ", "\t", "\n"])
    async def test_empty_task_id_raises(self, runtime, bad_id: str) -> None:
        """Empty or whitespace-only task_id raises ValueError."""
        with pytest.raises(ValueError, match="task_id must be non-empty"):
            await runtime.create_task(bad_id, "Title")


class TestListByStatusFallback:
    """list_by_status constructs synthetic snapshot when no persisted snapshot exists."""

    async def test_list_by_status_fallback_for_board_only_task(
        self,
        board,
        session_store,
    ) -> None:
        """Task created directly on board (no runtime.create_task) shows in list_by_status."""
        from swarmline.multi_agent.graph_task_types import GraphTaskItem
        from swarmline.multi_agent.task_types import TaskStatus

        rt = DefaultCodingTaskRuntime(board, session_store)

        # Create task directly on board, bypassing runtime → no snapshot
        item = GraphTaskItem(id="orphan-1", title="Orphan Task", status=TaskStatus.TODO)
        await board.create_task(item)

        pending = await rt.list_by_status(CodingTaskStatus.PENDING)
        orphan_snaps = [s for s in pending if s.task_id == "orphan-1"]
        assert len(orphan_snaps) == 1
        assert orphan_snaps[0].title == "Orphan Task"
        assert orphan_snaps[0].status == CodingTaskStatus.PENDING
        assert orphan_snaps[0].session_id == ""
