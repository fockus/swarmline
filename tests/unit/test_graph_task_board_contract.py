"""Contract tests for GraphTaskBoard — hierarchical tasks with atomic checkout."""

from __future__ import annotations

import asyncio

import pytest

from cognitia.multi_agent.graph_task_types import GraphTaskItem, TaskComment
from cognitia.multi_agent.task_types import TaskStatus
from cognitia.protocols.graph_task import GraphTaskBoard, TaskCommentStore


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
) -> GraphTaskItem:
    return GraphTaskItem(
        id=id,
        title=title,
        parent_task_id=parent_id,
        assignee_agent_id=assignee,
        goal_id=goal_id,
        dod_criteria=dod,
        status=status,
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
