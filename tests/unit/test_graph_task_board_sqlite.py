"""Unit: SqliteGraphTaskBoard — same contract as InMemory."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_task_board_sqlite import SqliteGraphTaskBoard
from swarmline.multi_agent.graph_task_types import GraphTaskItem, TaskComment
from swarmline.multi_agent.task_types import TaskStatus


@pytest.fixture
def board():
    return SqliteGraphTaskBoard(":memory:")


class TestCrud:
    async def test_create_and_list(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task 1"))
        tasks = await board.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t1"

    async def test_get_subtasks(self, board) -> None:
        await board.create_task(GraphTaskItem(id="root", title="Root"))
        await board.create_task(
            GraphTaskItem(id="sub1", title="Sub 1", parent_task_id="root")
        )
        await board.create_task(
            GraphTaskItem(id="sub2", title="Sub 2", parent_task_id="root")
        )
        subs = await board.get_subtasks("root")
        assert len(subs) == 2


class TestCheckout:
    async def test_checkout_locks_task(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        result = await board.checkout_task("t1", "agent-a")
        assert result is not None
        assert result.checkout_agent_id == "agent-a"

    async def test_second_checkout_returns_none(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        await board.checkout_task("t1", "agent-a")
        second = await board.checkout_task("t1", "agent-b")
        assert second is None

    async def test_checkout_nonexistent(self, board) -> None:
        result = await board.checkout_task("nope", "agent-a")
        assert result is None


class TestComplete:
    async def test_complete_requires_in_progress(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        ok = await board.complete_task("t1")
        assert ok is False
        tasks = await board.list_tasks()
        assert tasks[0].status == TaskStatus.TODO

    async def test_complete_sets_done(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        await board.checkout_task("t1", "agent-a")
        ok = await board.complete_task("t1")
        assert ok is True
        tasks = await board.list_tasks()
        assert tasks[0].status == TaskStatus.DONE

    async def test_propagation(self, board) -> None:
        await board.create_task(GraphTaskItem(id="root", title="Root"))
        await board.create_task(
            GraphTaskItem(id="s1", title="S1", parent_task_id="root")
        )
        await board.create_task(
            GraphTaskItem(id="s2", title="S2", parent_task_id="root")
        )
        await board.checkout_task("s1", "agent-a")
        await board.checkout_task("s2", "agent-b")
        await board.complete_task("s1")
        await board.complete_task("s2")
        tasks = await board.list_tasks()
        root = next(t for t in tasks if t.id == "root")
        assert root.status == TaskStatus.DONE


class TestHierarchyValidation:
    async def test_self_parent_rejected(self, board) -> None:
        with pytest.raises(ValueError, match="own parent"):
            await board.create_task(
                GraphTaskItem(id="t1", title="Task", parent_task_id="t1")
            )

    async def test_cycle_rejected_on_create(self, board) -> None:
        await board.create_task(GraphTaskItem(id="a", title="A", parent_task_id="b"))
        with pytest.raises(ValueError, match="Cycle"):
            await board.create_task(
                GraphTaskItem(id="b", title="B", parent_task_id="a")
            )


class TestComments:
    async def test_add_and_get(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        await board.add_comment(
            TaskComment(id="c1", task_id="t1", author_agent_id="a1", content="Hello")
        )
        comments = await board.get_comments("t1")
        assert len(comments) == 1
        assert comments[0].content == "Hello"

    async def test_thread(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        await board.add_comment(
            TaskComment(id="c1", task_id="t1", author_agent_id="a1", content="A")
        )
        await board.add_comment(
            TaskComment(id="c2", task_id="t1", author_agent_id="a2", content="B")
        )
        thread = await board.get_thread("t1")
        assert len(thread) == 2


class TestNamespaceIsolation:
    async def test_recursive_helpers_do_not_cross_namespace(self, tmp_path) -> None:
        db_path = tmp_path / "graph-task-board.sqlite3"
        board_a = SqliteGraphTaskBoard(str(db_path), namespace="goal-a")
        board_b = SqliteGraphTaskBoard(str(db_path), namespace="goal-b")

        await board_a.create_task(
            GraphTaskItem(id="root", title="Root", goal_id="goal-a")
        )
        await board_a.add_comment(
            TaskComment(
                id="c-root", task_id="root", author_agent_id="a1", content="Root note"
            )
        )

        await board_b.create_task(
            GraphTaskItem(
                id="child",
                title="Child",
                parent_task_id="root",
                goal_id="goal-b",
                dependencies=("root",),
            )
        )
        await board_b.add_comment(
            TaskComment(
                id="c-child",
                task_id="child",
                author_agent_id="a2",
                content="Child note",
            )
        )

        assert await board_a.get_subtasks("root") == []
        assert await board_b.get_comments("root") == []

        thread = await board_a.get_thread("root")
        assert [comment.id for comment in thread] == ["c-root"]

        ancestry = await board_b.get_goal_ancestry("child")
        assert ancestry is not None
        assert ancestry.root_goal_id == "goal-b"
        assert ancestry.chain == ("child",)

        assert await board_b.get_blocked_by("child") == []

        await board_b.checkout_task("child", "agent-b")
        assert await board_b.complete_task("child") is True

        root = next(task for task in await board_a.list_tasks() if task.id == "root")
        assert root.status == TaskStatus.TODO
        assert root.progress == 0.0


class TestGoalAncestry:
    async def test_ancestry_chain(self, board) -> None:
        await board.create_task(GraphTaskItem(id="root", title="Root", goal_id="g1"))
        await board.create_task(
            GraphTaskItem(id="sub", title="Sub", parent_task_id="root", goal_id="g1")
        )
        ancestry = await board.get_goal_ancestry("sub")
        assert ancestry is not None
        assert ancestry.root_goal_id == "g1"
        assert ancestry.chain == ("root", "sub")

    async def test_ancestry_no_goal(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="No goal"))
        assert await board.get_goal_ancestry("t1") is None


class TestSerialization:
    async def test_progress_stage_blocked_roundtrip(self, board) -> None:
        """New fields survive SQLite JSON roundtrip."""
        from dataclasses import replace

        task = GraphTaskItem(id="t1", title="Test")
        task = replace(task, progress=0.75, stage="review", blocked_reason="waiting")
        await board.create_task(task)
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.progress == 0.75
        assert t.stage == "review"
        assert t.blocked_reason == "waiting"


class TestBlockUnblock:
    async def test_block_task(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        result = await board.block_task("t1", "Waiting for dep")
        assert result is True
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.status == TaskStatus.BLOCKED
        assert t.blocked_reason == "Waiting for dep"

    async def test_unblock_task(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        await board.block_task("t1", "Waiting")
        result = await board.unblock_task("t1")
        assert result is True
        tasks = await board.list_tasks()
        t = tasks[0]
        assert t.status == TaskStatus.TODO
        assert t.blocked_reason == ""

    async def test_block_nonexistent(self, board) -> None:
        result = await board.block_task("nope", "reason")
        assert result is False

    async def test_unblock_non_blocked(self, board) -> None:
        await board.create_task(GraphTaskItem(id="t1", title="Task"))
        result = await board.unblock_task("t1")
        assert result is False
