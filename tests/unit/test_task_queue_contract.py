"""Contract tests for TaskQueue Protocol (Phase 9B-MVP).

Part 1: Protocol shape tests (runtime_checkable, ISP, async).
Part 2: Behavioral contract tests — run against every implementation
         via parametrized fixture. Adding a backend = adding one param.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING

import pytest

from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)
from swarmline.protocols.multi_agent import TaskQueue

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ValidTaskQueue:
    """Minimal valid implementation for protocol shape tests."""

    async def put(self, item: TaskItem) -> None:
        pass

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        return None

    async def complete(self, task_id: str) -> bool:
        return False

    async def cancel(self, task_id: str) -> bool:
        return False

    async def list_tasks(
        self, filters: TaskFilter | None = None,
    ) -> list[TaskItem]:
        return []


class _InvalidTaskQueue:
    """Missing methods -- should NOT pass isinstance check."""

    async def put(self, item: TaskItem) -> None:
        pass


def _task(
    tid: str,
    priority: TaskPriority = TaskPriority.MEDIUM,
    assignee: str | None = None,
) -> TaskItem:
    return TaskItem(
        id=tid,
        title=f"Task {tid}",
        priority=priority,
        assignee_agent_id=assignee,
    )


# ---------------------------------------------------------------------------
# Part 1: Protocol shape tests
# ---------------------------------------------------------------------------

class TestTaskQueueProtocol:
    """Contract tests for TaskQueue Protocol shape."""

    def test_task_queue_is_runtime_checkable(self) -> None:
        assert isinstance(_ValidTaskQueue(), TaskQueue)

    def test_task_queue_invalid_impl_fails_isinstance(self) -> None:
        assert not isinstance(_InvalidTaskQueue(), TaskQueue)

    def test_task_queue_has_exactly_five_methods(self) -> None:
        methods = [
            name
            for name, _ in inspect.getmembers(
                TaskQueue, predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        ]
        assert len(methods) == 5

    def test_task_queue_method_names(self) -> None:
        expected = {"put", "get", "complete", "cancel", "list_tasks"}
        methods = {
            name
            for name, _ in inspect.getmembers(
                TaskQueue, predicate=inspect.isfunction,
            )
            if not name.startswith("_")
        }
        assert methods == expected

    def test_task_queue_all_methods_are_async(self) -> None:
        for name in ("put", "get", "complete", "cancel", "list_tasks"):
            method = getattr(TaskQueue, name)
            assert inspect.iscoroutinefunction(method), (
                f"{name} must be async"
            )


# ---------------------------------------------------------------------------
# Part 2: Behavioral contract tests (parametrized fixture)
# ---------------------------------------------------------------------------

@pytest.fixture(params=["inmemory", "sqlite"])
def queue(request: pytest.FixtureRequest, tmp_path):
    """Parametrized queue — runs every test against all backends."""
    from swarmline.multi_agent.task_queue import InMemoryTaskQueue, SqliteTaskQueue

    if request.param == "inmemory":
        yield InMemoryTaskQueue()
        return

    q = SqliteTaskQueue(db_path=str(tmp_path / "tasks.db"))
    yield q
    q.close()


async def test_put_and_list_returns_all(queue) -> None:
    await queue.put(_task("a"))
    await queue.put(_task("b"))
    items = await queue.list_tasks()
    assert len(items) == 2
    assert {i.id for i in items} == {"a", "b"}


async def test_get_returns_highest_priority(queue) -> None:
    await queue.put(_task("low", TaskPriority.LOW))
    await queue.put(_task("crit", TaskPriority.CRITICAL))
    got = await queue.get()
    assert got is not None
    assert got.id == "crit"
    assert got.status == TaskStatus.IN_PROGRESS


async def test_get_with_filter_by_assignee(queue) -> None:
    await queue.put(_task("t1", assignee="agent-1"))
    await queue.put(_task("t2", assignee="agent-2"))
    got = await queue.get(TaskFilter(assignee_agent_id="agent-2"))
    assert got is not None
    assert got.id == "t2"
    assert got.status == TaskStatus.IN_PROGRESS


async def test_get_without_assignee_filter_skips_preassigned_tasks(queue) -> None:
    await queue.put(_task("t1", assignee="agent-1"))
    assert await queue.get() is None


async def test_get_claims_task_and_hides_it_from_followup_get(queue) -> None:
    await queue.put(_task("t1"))
    first = await queue.get()
    second = await queue.get()
    assert first is not None
    assert first.status == TaskStatus.IN_PROGRESS
    assert second is None


async def test_complete_marks_done(queue) -> None:
    await queue.put(_task("t1"))
    result = await queue.complete("t1")
    assert result is True
    items = await queue.list_tasks(TaskFilter(status=TaskStatus.DONE))
    assert len(items) == 1
    assert items[0].status == TaskStatus.DONE


async def test_cancel_marks_cancelled(queue) -> None:
    await queue.put(_task("t1"))
    result = await queue.cancel("t1")
    assert result is True
    items = await queue.list_tasks(TaskFilter(status=TaskStatus.CANCELLED))
    assert len(items) == 1
    assert items[0].status == TaskStatus.CANCELLED


async def test_get_returns_none_when_empty(queue) -> None:
    assert await queue.get() is None


async def test_complete_nonexistent_returns_false(queue) -> None:
    assert await queue.complete("no-such-id") is False


async def test_complete_already_done_returns_false(queue) -> None:
    await queue.put(_task("t1"))
    await queue.complete("t1")
    assert await queue.complete("t1") is False


async def test_cancel_already_cancelled_returns_false(queue) -> None:
    await queue.put(_task("t1"))
    await queue.cancel("t1")
    assert await queue.cancel("t1") is False


async def test_list_tasks_with_status_filter(queue) -> None:
    await queue.put(_task("t1"))
    await queue.put(_task("t2"))
    await queue.complete("t1")
    todo = await queue.list_tasks(TaskFilter(status=TaskStatus.TODO))
    assert len(todo) == 1
    assert todo[0].id == "t2"


async def test_list_tasks_with_priority_filter(queue) -> None:
    await queue.put(_task("lo", TaskPriority.LOW))
    await queue.put(_task("hi", TaskPriority.HIGH))
    high = await queue.list_tasks(TaskFilter(priority=TaskPriority.HIGH))
    assert len(high) == 1
    assert high[0].id == "hi"


async def test_get_skips_done_and_cancelled(queue) -> None:
    await queue.put(_task("t1"))
    await queue.put(_task("t2"))
    await queue.complete("t1")
    await queue.cancel("t2")
    assert await queue.get() is None


async def test_list_tasks_shows_claimed_task_as_in_progress(queue) -> None:
    await queue.put(_task("t1"))
    await queue.get()
    claimed = await queue.list_tasks(TaskFilter(status=TaskStatus.IN_PROGRESS))
    assert len(claimed) == 1
    assert claimed[0].id == "t1"


async def test_terminal_transition_race_has_single_winner(queue) -> None:
    await queue.put(_task("t1"))
    await queue.get()

    complete_ok, cancel_ok = await asyncio.gather(
        queue.complete("t1"),
        queue.cancel("t1"),
    )

    assert sum((complete_ok, cancel_ok)) == 1
    terminal = await queue.list_tasks()
    assert len(terminal) == 1
    assert terminal[0].status in {TaskStatus.DONE, TaskStatus.CANCELLED}
