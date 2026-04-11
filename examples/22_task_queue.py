"""Task queue: priority-based task management for multi-agent systems.

Demonstrates: InMemoryTaskQueue, TaskItem, TaskStatus, TaskPriority, TaskFilter.
No API keys required.
"""

import asyncio
import time

from swarmline.multi_agent.task_queue import (
    InMemoryTaskQueue,
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)


async def main() -> None:
    queue = InMemoryTaskQueue()

    # 1. Add tasks with different priorities
    print("=== Adding Tasks ===")
    tasks = [
        TaskItem(id="t1", title="Fix login bug", priority=TaskPriority.CRITICAL, created_at=time.time()),
        TaskItem(id="t2", title="Add dark mode", priority=TaskPriority.LOW, created_at=time.time()),
        TaskItem(id="t3", title="Write API docs", priority=TaskPriority.MEDIUM, created_at=time.time()),
        TaskItem(id="t4", title="Security audit", priority=TaskPriority.HIGH, created_at=time.time()),
        TaskItem(
            id="t5", title="Refactor auth module", priority=TaskPriority.MEDIUM,
            assignee_agent_id="agent-dev-1", created_at=time.time(),
        ),
    ]
    for task in tasks:
        await queue.put(task)
        print(f"  Added: [{task.priority.value}] {task.title}")

    # 2. Get highest-priority task (claims it as IN_PROGRESS)
    print("\n=== Get Next Task (priority order) ===")
    next_task = await queue.get()
    if next_task:
        print(f"  Claimed: {next_task.title} (priority={next_task.priority.value}, status={next_task.status.value})")

    # 3. List tasks with filters
    print("\n=== Filter Tasks ===")
    all_tasks = await queue.list_tasks()
    print(f"  Total: {len(all_tasks)}")

    todo_tasks = await queue.list_tasks(TaskFilter(status=TaskStatus.TODO))
    print(f"  TODO: {len(todo_tasks)}")

    medium_tasks = await queue.list_tasks(TaskFilter(priority=TaskPriority.MEDIUM))
    print(f"  MEDIUM priority: {len(medium_tasks)}")

    agent_tasks = await queue.list_tasks(TaskFilter(assignee_agent_id="agent-dev-1"))
    print(f"  Assigned to agent-dev-1: {len(agent_tasks)}")

    # 4. Complete and cancel tasks
    print("\n=== Complete / Cancel ===")
    if next_task:
        completed = await queue.complete(next_task.id)
        print(f"  Completed '{next_task.title}': {completed}")

    cancelled = await queue.cancel("t2")
    print(f"  Cancelled 'Add dark mode': {cancelled}")

    # 5. Final state
    print("\n=== Final State ===")
    for task in await queue.list_tasks():
        print(f"  [{task.status.value:11}] [{task.priority.value:8}] {task.title}")

    # 6. SqliteTaskQueue (persistent, same API)
    print("\n=== SqliteTaskQueue ===")
    print("# from swarmline.multi_agent.task_queue import SqliteTaskQueue")
    print("# persistent_queue = SqliteTaskQueue(db_path='tasks.db')")
    print("# await persistent_queue.put(TaskItem(id='t1', title='...'))")
    print("# task = await persistent_queue.get()  # survives restart")


if __name__ == "__main__":
    asyncio.run(main())
