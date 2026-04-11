"""Integration tests for TaskQueue (Phase 9B-MVP).

Tests cover full lifecycle, priority ordering, concurrent access,
and SQLite persistence across instances.
"""

from __future__ import annotations

import asyncio

import pytest

from swarmline.multi_agent.task_queue import InMemoryTaskQueue, SqliteTaskQueue
from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def queue(request: pytest.FixtureRequest, tmp_path):
    """Parametrized queue for tests that run against both backends."""
    if request.param == "inmemory":
        yield InMemoryTaskQueue()
        return

    q = SqliteTaskQueue(db_path=str(tmp_path / "tasks.db"))
    yield q
    q.close()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_task_queue_put_get_complete_lifecycle(queue) -> None:
    """Full lifecycle: put -> get -> complete -> list(done)."""
    # Arrange
    task = _task("lifecycle-1", TaskPriority.HIGH)

    # Act — put
    await queue.put(task)
    items_after_put = await queue.list_tasks()
    assert len(items_after_put) == 1
    assert items_after_put[0].status == TaskStatus.TODO

    # Act — get
    got = await queue.get()
    assert got is not None
    assert got.id == "lifecycle-1"
    assert got.priority == TaskPriority.HIGH
    assert got.status == TaskStatus.IN_PROGRESS

    claimed_items = await queue.list_tasks(TaskFilter(status=TaskStatus.IN_PROGRESS))
    assert len(claimed_items) == 1
    assert claimed_items[0].id == "lifecycle-1"

    # Act — complete
    completed = await queue.complete("lifecycle-1")
    assert completed is True

    # Assert — list with DONE filter shows the completed task
    done_items = await queue.list_tasks(TaskFilter(status=TaskStatus.DONE))
    assert len(done_items) == 1
    assert done_items[0].id == "lifecycle-1"
    assert done_items[0].status == TaskStatus.DONE

    # Assert — get returns None (no more TODO tasks)
    assert await queue.get() is None


@pytest.mark.integration
async def test_task_queue_priority_ordering_multiple_items(queue) -> None:
    """Put 5 items with different priorities; get returns highest first."""
    # Arrange
    tasks = [
        _task("low-1", TaskPriority.LOW),
        _task("med-1", TaskPriority.MEDIUM),
        _task("high-1", TaskPriority.HIGH),
        _task("crit-1", TaskPriority.CRITICAL),
        _task("med-2", TaskPriority.MEDIUM),
    ]
    for t in tasks:
        await queue.put(t)

    # Act & Assert — sequential get should return by priority order
    first = await queue.get()
    assert first is not None
    assert first.id == "crit-1"
    assert first.priority == TaskPriority.CRITICAL
    assert first.status == TaskStatus.IN_PROGRESS

    # Complete CRITICAL, next get should return HIGH
    await queue.complete("crit-1")
    second = await queue.get()
    assert second is not None
    assert second.id == "high-1"
    assert second.priority == TaskPriority.HIGH
    assert second.status == TaskStatus.IN_PROGRESS

    # Complete HIGH, next should be one of the MEDIUM tasks
    await queue.complete("high-1")
    third = await queue.get()
    assert third is not None
    assert third.priority == TaskPriority.MEDIUM
    assert third.status == TaskStatus.IN_PROGRESS


@pytest.mark.integration
async def test_task_queue_concurrent_get_no_duplicate(queue) -> None:
    """Multiple concurrent get() calls may claim a task at most once."""
    # Arrange
    await queue.put(_task("only-one", TaskPriority.CRITICAL))

    # Act — fire 10 concurrent get() calls
    results = await asyncio.gather(*[queue.get() for _ in range(10)])

    # Assert — only one caller can claim the task
    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1
    assert non_none[0].id == "only-one"
    assert non_none[0].status == TaskStatus.IN_PROGRESS

    # Verify that after completing, no further get returns this item
    await queue.complete("only-one")
    after_complete = await asyncio.gather(*[queue.get() for _ in range(10)])
    assert all(r is None for r in after_complete)


@pytest.mark.integration
async def test_task_queue_get_without_filter_skips_preassigned_tasks(queue) -> None:
    await queue.put(_task("assigned", TaskPriority.CRITICAL, assignee="agent-1"))
    await queue.put(_task("free", TaskPriority.HIGH))

    got = await queue.get()

    assert got is not None
    assert got.id == "free"
    assert got.status == TaskStatus.IN_PROGRESS


@pytest.mark.integration
async def test_task_queue_get_with_assignee_filter_claims_matching_task(queue) -> None:
    await queue.put(_task("assigned-a", TaskPriority.CRITICAL, assignee="agent-1"))
    await queue.put(_task("assigned-b", TaskPriority.HIGH, assignee="agent-2"))

    got = await queue.get(TaskFilter(assignee_agent_id="agent-2"))

    assert got is not None
    assert got.id == "assigned-b"
    assert got.status == TaskStatus.IN_PROGRESS


@pytest.mark.integration
async def test_sqlite_task_queue_persistence(tmp_path) -> None:
    """SqliteTaskQueue preserves tasks across separate instances."""
    db_path = str(tmp_path / "persist.db")

    # Arrange — create first instance, put tasks
    q1 = SqliteTaskQueue(db_path=db_path)
    await q1.put(_task("persist-1", TaskPriority.HIGH))
    await q1.put(_task("persist-2", TaskPriority.LOW))
    await q1.complete("persist-1")
    q1.close()

    # Act — create a new instance with the same db_path
    q2 = SqliteTaskQueue(db_path=db_path)
    all_tasks = await q2.list_tasks()
    todo_tasks = await q2.list_tasks(TaskFilter(status=TaskStatus.TODO))
    done_tasks = await q2.list_tasks(TaskFilter(status=TaskStatus.DONE))

    # Assert — all data survived the instance swap
    assert len(all_tasks) == 2
    assert len(done_tasks) == 1
    assert done_tasks[0].id == "persist-1"
    assert done_tasks[0].status == TaskStatus.DONE
    assert len(todo_tasks) == 1
    assert todo_tasks[0].id == "persist-2"
    claimed = await q2.get()
    assert claimed is not None
    assert claimed.id == "persist-2"
    assert claimed.status == TaskStatus.IN_PROGRESS
    q2.close()

    q3 = SqliteTaskQueue(db_path=db_path)
    in_progress = await q3.list_tasks(TaskFilter(status=TaskStatus.IN_PROGRESS))
    assert len(in_progress) == 1
    assert in_progress[0].id == "persist-2"
    q3.close()


@pytest.mark.integration
async def test_sqlite_task_queue_terminal_transition_race_has_single_winner(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "race.db")
    queue = SqliteTaskQueue(db_path=db_path)
    await queue.put(_task("race-1", TaskPriority.HIGH))
    await queue.get()

    complete_ok, cancel_ok = await asyncio.gather(
        queue.complete("race-1"),
        queue.cancel("race-1"),
    )

    assert sum((complete_ok, cancel_ok)) == 1
    final_items = await queue.list_tasks()
    assert len(final_items) == 1
    assert final_items[0].status in {TaskStatus.DONE, TaskStatus.CANCELLED}
    queue.close()


@pytest.mark.integration
async def test_task_queue_get_filters_in_sql(tmp_path) -> None:
    """get() should filter at SQL level, not fetch all rows and filter in Python.

    Creates 100 tasks (90 done, 10 todo). get() must return a todo task
    and only todo tasks should be candidates.
    """
    db_path = str(tmp_path / "perf.db")
    queue = SqliteTaskQueue(db_path=db_path)

    # Arrange: insert 90 done tasks and 10 todo tasks
    for i in range(90):
        done_task = TaskItem(
            id=f"done-{i}",
            title=f"Done task {i}",
            status=TaskStatus.DONE,
            priority=TaskPriority.LOW,
        )
        await queue.put(done_task)

    priorities = [
        TaskPriority.LOW,
        TaskPriority.MEDIUM,
        TaskPriority.HIGH,
        TaskPriority.CRITICAL,
        TaskPriority.LOW,
        TaskPriority.MEDIUM,
        TaskPriority.HIGH,
        TaskPriority.LOW,
        TaskPriority.MEDIUM,
        TaskPriority.LOW,
    ]
    for i in range(10):
        todo_task = TaskItem(
            id=f"todo-{i}",
            title=f"Todo task {i}",
            status=TaskStatus.TODO,
            priority=priorities[i],
        )
        await queue.put(todo_task)

    # Act: get() should return the highest-priority todo task
    claimed = await queue.get()

    # Assert
    assert claimed is not None
    assert claimed.status == TaskStatus.IN_PROGRESS
    # The critical task (todo-3) should be claimed first
    assert claimed.id == "todo-3"
    assert claimed.priority == TaskPriority.CRITICAL

    # Verify that done tasks remain untouched
    done_items = await queue.list_tasks(TaskFilter(status=TaskStatus.DONE))
    assert len(done_items) == 90

    # Verify remaining todo tasks
    todo_items = await queue.list_tasks(TaskFilter(status=TaskStatus.TODO))
    assert len(todo_items) == 9  # One was claimed

    queue.close()
