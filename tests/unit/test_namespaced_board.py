"""Tests for namespace isolation on InMemoryGraphTaskBoard (COG-01)."""

from __future__ import annotations

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.protocols.graph_task import GraphTaskBoard


def _task(id: str, title: str = "Task", **kwargs) -> GraphTaskItem:
    return GraphTaskItem(id=id, title=title, **kwargs)


# ---------------------------------------------------------------------------
# Default namespace backward compat
# ---------------------------------------------------------------------------


class TestDefaultNamespace:
    def test_default_namespace_is_empty_string(self) -> None:
        board = InMemoryGraphTaskBoard()
        assert board.namespace == ""

    def test_default_board_satisfies_protocol(self) -> None:
        board = InMemoryGraphTaskBoard()
        assert isinstance(board, GraphTaskBoard)

    async def test_default_board_create_and_list(self) -> None:
        board = InMemoryGraphTaskBoard()
        await board.create_task(_task("t1"))
        tasks = await board.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t1"


# ---------------------------------------------------------------------------
# Namespace isolation
# ---------------------------------------------------------------------------


class TestNamespaceIsolation:
    async def test_explicit_namespace(self) -> None:
        board = InMemoryGraphTaskBoard(namespace="goal-a")
        assert board.namespace == "goal-a"

    async def test_tasks_isolated_between_namespaces(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("t1", "Task A"))
        tasks_b = await board_b.list_tasks()
        assert tasks_b == []

    async def test_own_tasks_visible(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        await board_a.create_task(_task("t1", "Task A"))
        tasks_a = await board_a.list_tasks()
        assert len(tasks_a) == 1
        assert tasks_a[0].id == "t1"

    async def test_checkout_from_other_namespace_returns_none(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("t1"))
        result = await board_b.checkout_task("t1", "agent-1")
        assert result is None

    async def test_complete_from_other_namespace_returns_false(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("t1"))
        result = await board_b.complete_task("t1")
        assert result is False

    async def test_subtasks_isolated(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("parent"))
        await board_a.create_task(_task("child", parent_task_id="parent"))
        subtasks = await board_b.get_subtasks("parent")
        assert subtasks == []

    async def test_own_subtasks_visible(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        await board_a.create_task(_task("parent"))
        await board_a.create_task(_task("child", parent_task_id="parent"))
        subtasks = await board_a.get_subtasks("parent")
        assert len(subtasks) == 1

    async def test_multiple_boards_independent(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("t1"))
        await board_a.create_task(_task("t2"))
        await board_b.create_task(_task("t3"))

        assert len(await board_a.list_tasks()) == 2
        assert len(await board_b.list_tasks()) == 1


# ---------------------------------------------------------------------------
# Namespace property
# ---------------------------------------------------------------------------


class TestNamespaceProperty:
    def test_namespace_property_returns_value(self) -> None:
        board = InMemoryGraphTaskBoard(namespace="my-ns")
        assert board.namespace == "my-ns"


# ---------------------------------------------------------------------------
# Ready tasks / blocked_by isolated
# ---------------------------------------------------------------------------


class TestNamespacedScheduling:
    async def test_get_ready_tasks_isolated(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("t1"))
        await board_b.create_task(_task("t2"))

        ready_a = await board_a.get_ready_tasks()
        assert len(ready_a) == 1
        assert ready_a[0].id == "t1"

    async def test_blocked_by_isolated(self) -> None:
        board_a = InMemoryGraphTaskBoard(namespace="goal-a")
        board_b = InMemoryGraphTaskBoard(namespace="goal-b")

        await board_a.create_task(_task("dep"))
        await board_a.create_task(_task("t1", dependencies=("dep",)))
        # board_b should not see t1
        blockers = await board_b.get_blocked_by("t1")
        assert blockers == []
