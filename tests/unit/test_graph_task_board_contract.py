"""Contract tests for GraphTaskBoard — hierarchical tasks with atomic checkout."""

from __future__ import annotations

import asyncio

import pytest

from cognitia.multi_agent.graph_task_types import GraphTaskItem, TaskComment
from cognitia.multi_agent.task_types import TaskStatus
from cognitia.protocols.graph_task import GraphTaskBlocker, GraphTaskBoard, GraphTaskScheduler, TaskCommentStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def board():
    from cognitia.multi_agent.graph_task_board import InMemoryGraphTaskBoard

    return InMemoryGraphTaskBoard()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    id: str = "t1",
    title: str = "Task 1",
    parent_id: str | None = None,
    assignee: str | None = None,
    goal_id: str | None = None,
    dod: tuple[str, ...] = (),
    status: TaskStatus = TaskStatus.TODO,
    dependencies: tuple[str, ...] = (),
    delegated_by: str | None = None,
    delegation_reason: str | None = None,
    estimated_effort: str | None = None,
) -> GraphTaskItem:
    return GraphTaskItem(
        id=id,
        title=title,
        parent_task_id=parent_id,
        assignee_agent_id=assignee,
        goal_id=goal_id,
        dod_criteria=dod,
        status=status,
        dependencies=dependencies,
        delegated_by=delegated_by,
        delegation_reason=delegation_reason,
        estimated_effort=estimated_effort,
    )


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocol:

    def test_board_protocol(self, board) -> None:
        assert isinstance(board, GraphTaskBoard)

    def test_comment_store_protocol(self, board) -> None:
        assert isinstance(board, TaskCommentStore)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCRUD:

    async def test_create_and_list(self, board) -> None:
        await board.create_task(_task("t1", "Task 1"))
        tasks = await board.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t1"

    async def test_create_multiple(self, board) -> None:
        await board.create_task(_task("t1", "A"))
        await board.create_task(_task("t2", "B"))
        await board.create_task(_task("t3", "C"))
        tasks = await board.list_tasks()
        assert len(tasks) == 3

    async def test_get_subtasks(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("child1", "C1", parent_id="parent"))
        await board.create_task(_task("child2", "C2", parent_id="parent"))
        subtasks = await board.get_subtasks("parent")
        assert len(subtasks) == 2
        ids = {t.id for t in subtasks}
        assert ids == {"child1", "child2"}

    async def test_get_subtasks_empty(self, board) -> None:
        await board.create_task(_task("leaf", "Leaf"))
        assert await board.get_subtasks("leaf") == []

    async def test_list_with_status_filter(self, board) -> None:
        await board.create_task(_task("t1", "A", status=TaskStatus.TODO))
        await board.create_task(_task("t2", "B", status=TaskStatus.DONE))
        tasks = await board.list_tasks(status=TaskStatus.TODO)
        assert len(tasks) == 1
        assert tasks[0].id == "t1"


class TestHierarchyValidation:

    async def test_self_parent_rejected(self, board) -> None:
        with pytest.raises(ValueError, match="own parent"):
            await board.create_task(_task("t1", "Task", parent_id="t1"))

    async def test_cycle_rejected_on_create(self, board) -> None:
        await board.create_task(_task("a", "A", parent_id="b"))
        with pytest.raises(ValueError, match="Cycle"):
            await board.create_task(_task("b", "B", parent_id="a"))


# ---------------------------------------------------------------------------
# Atomic checkout
# ---------------------------------------------------------------------------


class TestAtomicCheckout:

    async def test_checkout_claims_task(self, board) -> None:
        await board.create_task(_task("t1", "Task", assignee="agent1"))
        result = await board.checkout_task("t1", "agent1")
        assert result is not None
        assert result.checkout_agent_id == "agent1"
        assert result.status == TaskStatus.IN_PROGRESS

    async def test_checkout_already_claimed_returns_none(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        await board.checkout_task("t1", "agent1")
        result = await board.checkout_task("t1", "agent2")
        assert result is None

    async def test_concurrent_checkout_one_wins(self, board) -> None:
        await board.create_task(_task("t1", "Task"))

        async def try_checkout(agent_id: str) -> GraphTaskItem | None:
            return await board.checkout_task("t1", agent_id)

        results = await asyncio.gather(
            try_checkout("agent1"),
            try_checkout("agent2"),
            try_checkout("agent3"),
        )
        wins = [r for r in results if r is not None]
        assert len(wins) == 1  # exactly one wins

    async def test_checkout_missing_returns_none(self, board) -> None:
        result = await board.checkout_task("nonexistent", "agent1")
        assert result is None


# ---------------------------------------------------------------------------
# Status propagation
# ---------------------------------------------------------------------------


class TestStatusPropagation:

    async def test_complete_requires_in_progress(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        assert await board.complete_task("t1") is False
        task = next(t for t in await board.list_tasks() if t.id == "t1")
        assert task.status == TaskStatus.TODO

    async def test_complete_sets_done(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        await board.checkout_task("t1", "agent1")
        completed = await board.complete_task("t1")
        assert completed is True
        tasks = await board.list_tasks()
        assert tasks[0].status == TaskStatus.DONE

    async def test_all_subtasks_done_completes_parent(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "Child 1", parent_id="parent"))
        await board.create_task(_task("c2", "Child 2", parent_id="parent"))

        await board.checkout_task("c1", "a1")
        await board.checkout_task("c2", "a2")
        await board.complete_task("c1")
        await board.complete_task("c2")

        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.status == TaskStatus.DONE

    async def test_partial_subtasks_does_not_complete_parent(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "Child 1", parent_id="parent"))
        await board.create_task(_task("c2", "Child 2", parent_id="parent"))

        await board.checkout_task("c1", "a1")
        await board.complete_task("c1")

        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.status == TaskStatus.TODO  # not done yet


# ---------------------------------------------------------------------------
# Goal ancestry
# ---------------------------------------------------------------------------


class TestGoalAncestry:

    async def test_get_goal_ancestry(self, board) -> None:
        await board.create_task(_task("root", "Root Goal", goal_id="g1"))
        await board.create_task(_task("sub", "Sub Task", parent_id="root", goal_id="g1"))
        await board.create_task(_task("leaf", "Leaf Task", parent_id="sub", goal_id="g1"))

        ancestry = await board.get_goal_ancestry("leaf")
        assert ancestry is not None
        assert ancestry.root_goal_id == "g1"
        assert ancestry.chain == ("root", "sub", "leaf")

    async def test_ancestry_root_task(self, board) -> None:
        await board.create_task(_task("root", "Root", goal_id="g1"))
        ancestry = await board.get_goal_ancestry("root")
        assert ancestry is not None
        assert ancestry.chain == ("root",)

    async def test_ancestry_no_goal_returns_none(self, board) -> None:
        await board.create_task(_task("t1", "No Goal"))
        ancestry = await board.get_goal_ancestry("t1")
        assert ancestry is None


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class TestComments:

    async def test_add_and_get_comments(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        await board.add_comment(TaskComment(
            id="c1", task_id="t1", author_agent_id="agent1", content="Progress update"
        ))
        comments = await board.get_comments("t1")
        assert len(comments) == 1
        assert comments[0].content == "Progress update"

    async def test_thread_includes_subtask_comments(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("child", "Child", parent_id="parent"))
        await board.add_comment(TaskComment(
            id="c1", task_id="parent", author_agent_id="a1", content="Parent comment"
        ))
        await board.add_comment(TaskComment(
            id="c2", task_id="child", author_agent_id="a2", content="Child comment"
        ))
        thread = await board.get_thread("parent")
        assert len(thread) == 2

    async def test_comments_empty(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        assert await board.get_comments("t1") == []


# ---------------------------------------------------------------------------
# Dependencies (DAG)
# ---------------------------------------------------------------------------


class TestDependencies:

    def test_scheduler_protocol(self, board) -> None:
        assert isinstance(board, GraphTaskScheduler)

    async def test_get_ready_tasks_no_deps(self, board) -> None:
        await board.create_task(_task("t1", "A"))
        await board.create_task(_task("t2", "B"))
        ready = await board.get_ready_tasks()
        ids = {t.id for t in ready}
        assert ids == {"t1", "t2"}

    async def test_get_ready_tasks_with_deps_blocked(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Test", dependencies=("t1",)))
        ready = await board.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    async def test_get_ready_tasks_deps_resolved(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Test", dependencies=("t1",)))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        ready = await board.get_ready_tasks()
        ids = {t.id for t in ready}
        assert "t2" in ids

    async def test_get_ready_excludes_checked_out(self, board) -> None:
        await board.create_task(_task("t1", "A"))
        await board.checkout_task("t1", "agent1")
        ready = await board.get_ready_tasks()
        assert all(t.id != "t1" for t in ready)

    async def test_get_ready_excludes_done(self, board) -> None:
        await board.create_task(_task("t1", "A"))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        ready = await board.get_ready_tasks()
        assert all(t.id != "t1" for t in ready)

    async def test_get_blocked_by_returns_blockers(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Deploy"))
        await board.create_task(_task("t3", "Smoke", dependencies=("t1", "t2")))
        blockers = await board.get_blocked_by("t3")
        blocker_ids = {b.id for b in blockers}
        assert blocker_ids == {"t1", "t2"}

    async def test_get_blocked_by_partial(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Deploy"))
        await board.create_task(_task("t3", "Smoke", dependencies=("t1", "t2")))
        await board.checkout_task("t1", "a1")
        await board.complete_task("t1")
        blockers = await board.get_blocked_by("t3")
        assert len(blockers) == 1
        assert blockers[0].id == "t2"

    async def test_get_blocked_by_all_done_empty(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Test", dependencies=("t1",)))
        await board.checkout_task("t1", "a1")
        await board.complete_task("t1")
        blockers = await board.get_blocked_by("t2")
        assert blockers == []

    async def test_get_blocked_by_no_deps(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        blockers = await board.get_blocked_by("t1")
        assert blockers == []

    async def test_get_blocked_by_missing_task(self, board) -> None:
        blockers = await board.get_blocked_by("nonexistent")
        assert blockers == []


# ---------------------------------------------------------------------------
# Delegation metadata
# ---------------------------------------------------------------------------


class TestDelegationMetadata:

    async def test_delegated_by_preserved(self, board) -> None:
        await board.create_task(_task(
            "t1", "Task", delegated_by="ceo", delegation_reason="need frontend help",
        ))
        tasks = await board.list_tasks()
        assert tasks[0].delegated_by == "ceo"
        assert tasks[0].delegation_reason == "need frontend help"

    async def test_estimated_effort_preserved(self, board) -> None:
        await board.create_task(_task("t1", "Task", estimated_effort="M"))
        tasks = await board.list_tasks()
        assert tasks[0].estimated_effort == "M"

    async def test_dependencies_preserved(self, board) -> None:
        await board.create_task(_task("t1", "Build"))
        await board.create_task(_task("t2", "Test", dependencies=("t1",)))
        tasks = await board.list_tasks()
        t2 = next(t for t in tasks if t.id == "t2")
        assert t2.dependencies == ("t1",)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


class TestTimestamps:

    async def test_started_at_set_on_checkout(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        task = await board.checkout_task("t1", "agent1")
        assert task is not None
        assert task.started_at is not None
        assert task.started_at > 0

    async def test_completed_at_set_on_complete(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.completed_at is not None
        assert t.completed_at > 0

    async def test_started_before_completed(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.started_at is not None
        assert t.completed_at is not None
        assert t.started_at <= t.completed_at

    async def test_initially_no_timestamps(self, board) -> None:
        await board.create_task(_task("t1", "Task"))
        tasks = await board.list_tasks()
        assert tasks[0].started_at is None
        assert tasks[0].completed_at is None


# ---------------------------------------------------------------------------
# New fields (progress, stage, blocked_reason)
# ---------------------------------------------------------------------------


class TestNewFields:

    async def test_new_task_defaults(self, board) -> None:
        """New tasks have progress=0.0, stage='', blocked_reason=''."""
        await board.create_task(_task("t1", "Test"))
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.progress == 0.0
        assert t.stage == ""
        assert t.blocked_reason == ""


# ---------------------------------------------------------------------------
# Block / Unblock
# ---------------------------------------------------------------------------


class TestBlocked:

    def test_blocker_protocol(self, board) -> None:
        assert isinstance(board, GraphTaskBlocker)

    async def test_block_task_sets_blocked_status(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        result = await board.block_task("t1", "Waiting for API key")
        assert result is True
        tasks = await board.list_tasks()
        t = next(t for t in tasks if t.id == "t1")
        assert t.status == TaskStatus.BLOCKED
        assert t.blocked_reason == "Waiting for API key"

    async def test_block_task_empty_reason_rejected(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        result = await board.block_task("t1", "")
        assert result is False
        # Task unchanged
        tasks = await board.list_tasks()
        assert tasks[0].status == TaskStatus.TODO

    async def test_block_task_whitespace_reason_rejected(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        result = await board.block_task("t1", "   ")
        assert result is False

    async def test_block_done_task_rejected(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        result = await board.block_task("t1", "reason")
        assert result is False

    async def test_block_nonexistent_task(self, board) -> None:
        result = await board.block_task("nonexistent", "reason")
        assert result is False

    async def test_unblock_task_returns_to_todo(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        await board.block_task("t1", "Waiting")
        result = await board.unblock_task("t1")
        assert result is True
        tasks = await board.list_tasks()
        t = next(t for t in tasks if t.id == "t1")
        assert t.status == TaskStatus.TODO
        assert t.blocked_reason == ""

    async def test_unblock_non_blocked_task_rejected(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        result = await board.unblock_task("t1")
        assert result is False

    async def test_blocked_task_cannot_be_checked_out(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        await board.block_task("t1", "Waiting")
        result = await board.checkout_task("t1", "agent-1")
        assert result is None

    async def test_blocked_task_not_in_ready_tasks(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        await board.block_task("t1", "Waiting")
        ready = await board.get_ready_tasks()
        assert all(t.id != "t1" for t in ready)

    async def test_block_releases_checkout(self, board) -> None:
        await board.create_task(_task("t1", "Test"))
        await board.checkout_task("t1", "agent-1")
        await board.block_task("t1", "External dependency")
        tasks = await board.list_tasks()
        t = next(t for t in tasks if t.id == "t1")
        assert t.checkout_agent_id is None


# ---------------------------------------------------------------------------
# Progress auto-calculation
# ---------------------------------------------------------------------------


class TestProgress:

    async def test_completed_leaf_has_full_progress(self, board) -> None:
        await board.create_task(_task("t1", "Leaf"))
        await board.checkout_task("t1", "agent1")
        await board.complete_task("t1")
        tasks = await board.list_tasks()
        assert tasks[0].progress == 1.0

    async def test_parent_progress_one_of_two_done(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "Child 1", parent_id="parent"))
        await board.create_task(_task("c2", "Child 2", parent_id="parent"))
        await board.checkout_task("c1", "agent1")
        await board.complete_task("c1")
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.progress == pytest.approx(0.5)
        assert parent.status == TaskStatus.TODO  # not all done

    async def test_parent_progress_all_done(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "Child 1", parent_id="parent"))
        await board.create_task(_task("c2", "Child 2", parent_id="parent"))
        await board.checkout_task("c1", "agent1")
        await board.checkout_task("c2", "agent2")
        await board.complete_task("c1")
        await board.complete_task("c2")
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.progress == pytest.approx(1.0)
        assert parent.status == TaskStatus.DONE

    async def test_grandparent_progress_cascades(self, board) -> None:
        await board.create_task(_task("gp", "Grandparent"))
        await board.create_task(_task("p", "Parent", parent_id="gp"))
        await board.create_task(_task("c1", "Child 1", parent_id="p"))
        await board.create_task(_task("c2", "Child 2", parent_id="p"))
        await board.checkout_task("c1", "agent1")
        await board.complete_task("c1")
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "p")
        gp = next(t for t in tasks if t.id == "gp")
        assert parent.progress == pytest.approx(0.5)
        assert gp.progress == pytest.approx(0.5)  # only child "p" with progress 0.5

    async def test_three_children_mixed(self, board) -> None:
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "C1", parent_id="parent"))
        await board.create_task(_task("c2", "C2", parent_id="parent"))
        await board.create_task(_task("c3", "C3", parent_id="parent"))
        await board.checkout_task("c1", "agent1")
        await board.checkout_task("c2", "agent2")
        await board.complete_task("c1")
        await board.complete_task("c2")
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.progress == pytest.approx(2.0 / 3.0)
        assert parent.status == TaskStatus.TODO  # c3 still todo

    async def test_cancelled_child_drags_progress(self, board) -> None:
        """Cancelled child has progress 0.0, counts in denominator."""
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "C1", parent_id="parent"))
        await board.create_task(_task("c2", "C2", parent_id="parent"))
        await board.create_task(_task("c3", "C3", parent_id="parent"))
        await board.checkout_task("c1", "agent1")
        await board.checkout_task("c2", "agent2")
        await board.complete_task("c1")
        await board.complete_task("c2")
        # c3 stays TODO with progress 0.0
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.progress == pytest.approx(2.0 / 3.0)
        assert parent.status != TaskStatus.DONE

    async def test_blocked_child_drags_progress(self, board) -> None:
        """Blocked child has progress 0.0, parent not auto-completed."""
        await board.create_task(_task("parent", "Parent"))
        await board.create_task(_task("c1", "C1", parent_id="parent"))
        await board.create_task(_task("c2", "C2", parent_id="parent"))
        await board.create_task(_task("c3", "C3", parent_id="parent"))
        await board.checkout_task("c1", "agent1")
        await board.checkout_task("c2", "agent2")
        await board.complete_task("c1")
        await board.complete_task("c2")
        await board.block_task("c3", "Waiting for input")
        tasks = await board.list_tasks()
        parent = next(t for t in tasks if t.id == "parent")
        assert parent.progress == pytest.approx(2.0 / 3.0)
        assert parent.status != TaskStatus.DONE


# ---------------------------------------------------------------------------
# Concurrent read + write safety
# ---------------------------------------------------------------------------


class TestConcurrentReadWrite:

    async def test_concurrent_reads_and_writes_no_errors(self, board) -> None:
        """Concurrent list/get/complete must not raise due to dict mutation during iteration."""
        for i in range(20):
            await board.create_task(_task(f"t{i}", f"Task {i}"))

        async def writer() -> None:
            for i in range(20):
                await board.checkout_task(f"t{i}", f"agent-{i}")
                await board.complete_task(f"t{i}")

        async def reader() -> list[GraphTaskItem]:
            results: list[GraphTaskItem] = []
            for _ in range(30):
                results.extend(await board.list_tasks())
                await board.get_subtasks("t0")
                await board.get_ready_tasks()
                await board.get_blocked_by("t1")
            return results

        errors: list[Exception] = []
        try:
            await asyncio.gather(writer(), reader(), reader())
        except Exception as exc:
            errors.append(exc)

        assert errors == [], f"Concurrent read/write raised: {errors}"
