"""In-memory hierarchical task board with atomic checkout and status propagation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

from swarmline.multi_agent.graph_task_types import (
    GoalAncestry,
    GraphTaskItem,
    TaskComment,
)
from swarmline.multi_agent.task_types import TaskStatus


class InMemoryGraphTaskBoard:
    """In-memory implementation of GraphTaskBoard + TaskCommentStore.

    Supports namespace isolation: each board instance operates on its own
    namespace. Tasks created in one namespace are invisible to boards
    with a different namespace. Default namespace '' preserves backward compat.
    """

    def __init__(self, namespace: str = "") -> None:
        self._namespace = namespace
        self._tasks: dict[str, GraphTaskItem] = {}
        self._comments: list[TaskComment] = []
        self._lock = asyncio.Lock()

    @property
    def namespace(self) -> str:
        """Return the namespace this board operates on."""
        return self._namespace

    # --- GraphTaskBoard (5 methods) ---

    async def create_task(self, task: GraphTaskItem) -> None:
        async with self._lock:
            self._validate_parent_link(task)
            self._tasks[task.id] = task

    async def checkout_task(self, task_id: str, agent_id: str) -> GraphTaskItem | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.checkout_agent_id is not None:
                return None  # already claimed
            if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                return None
            updated = replace(
                task,
                checkout_agent_id=agent_id,
                status=TaskStatus.IN_PROGRESS,
                started_at=time.time(),
            )
            self._tasks[task_id] = updated
            return updated

    async def complete_task(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status != TaskStatus.IN_PROGRESS:
                return False
            self._tasks[task_id] = replace(
                task,
                status=TaskStatus.DONE,
                completed_at=time.time(),
                progress=1.0,
            )
            # Auto-propagate progress and completion upward
            self._propagate_parent(task.parent_task_id)
            return True

    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]:
        async with self._lock:
            return [t for t in self._tasks.values() if t.parent_task_id == task_id]

    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]:
        async with self._lock:
            result = list(self._tasks.values())
            if "status" in filters:
                result = [t for t in result if t.status == filters["status"]]
            if "assignee_agent_id" in filters:
                result = [
                    t
                    for t in result
                    if t.assignee_agent_id == filters["assignee_agent_id"]
                ]
            if "priority" in filters:
                result = [t for t in result if t.priority == filters["priority"]]
            return result

    # --- TaskCommentStore (3 methods) ---

    async def add_comment(self, comment: TaskComment) -> None:
        self._comments.append(comment)

    async def get_comments(self, task_id: str) -> list[TaskComment]:
        return [c for c in self._comments if c.task_id == task_id]

    async def get_thread(self, task_id: str) -> list[TaskComment]:
        """Get all comments for a task and its subtasks (recursive)."""
        async with self._lock:
            task_ids = self._collect_subtree_task_ids(task_id)
            return [c for c in self._comments if c.task_id in task_ids]

    # --- GraphTaskScheduler (2 methods) ---

    async def get_ready_tasks(self) -> list[GraphTaskItem]:
        """Return tasks that are TODO, not checked out, and have all dependencies DONE."""
        async with self._lock:
            ready: list[GraphTaskItem] = []
            for task in self._tasks.values():
                if task.status != TaskStatus.TODO:
                    continue
                if task.checkout_agent_id is not None:
                    continue
                if task.dependencies and not self._all_deps_done(task.dependencies):
                    continue
                ready.append(task)
            return ready

    async def get_blocked_by(self, task_id: str) -> list[GraphTaskItem]:
        """Return dependency tasks that are not yet DONE."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return []
            blockers: list[GraphTaskItem] = []
            for dep_id in task.dependencies:
                dep = self._tasks.get(dep_id)
                if dep is not None and dep.status != TaskStatus.DONE:
                    blockers.append(dep)
            return blockers

    def _all_deps_done(self, dep_ids: tuple[str, ...]) -> bool:
        for dep_id in dep_ids:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True

    # --- GraphTaskBlocker (2 methods) ---

    async def block_task(self, task_id: str, reason: str) -> bool:
        """Block a task with a mandatory reason."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if not reason or not reason.strip():
                return False
            if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                return False
            self._tasks[task_id] = replace(
                task,
                status=TaskStatus.BLOCKED,
                blocked_reason=reason.strip(),
                checkout_agent_id=None,  # release checkout if blocked
            )
            return True

    async def unblock_task(self, task_id: str) -> bool:
        """Unblock a task, returning it to TODO status."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status != TaskStatus.BLOCKED:
                return False
            self._tasks[task_id] = replace(
                task,
                status=TaskStatus.TODO,
                blocked_reason="",
            )
            return True

    # --- Cancel (not part of core GraphTaskBoard protocol — ISP) ---

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Sets status to CANCELLED and releases checkout.

        Returns True if the task was found and cancelled, False otherwise.
        Only tasks in TODO or IN_PROGRESS can be cancelled.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                return False
            self._tasks[task_id] = replace(
                task,
                status=TaskStatus.CANCELLED,
                checkout_agent_id=None,
                completed_at=time.time(),
            )
            return True

    # --- Extra: GoalAncestry ---

    async def get_goal_ancestry(self, task_id: str) -> GoalAncestry | None:
        """Walk parent_task_id chain to build goal ancestry."""
        async with self._lock:
            chain: list[str] = []
            current_id: str | None = task_id
            goal_id: str | None = None
            visited: set[str] = set()

            while current_id and current_id not in visited:
                visited.add(current_id)
                task = self._tasks.get(current_id)
                if task is None:
                    break
                chain.append(current_id)
                if task.goal_id and goal_id is None:
                    goal_id = task.goal_id
                current_id = task.parent_task_id

            if goal_id is None:
                return None

            chain.reverse()  # root to leaf
            return GoalAncestry(root_goal_id=goal_id, chain=tuple(chain))

    # --- Internal ---

    def _validate_parent_link(self, task: GraphTaskItem) -> None:
        """Reject self-parenting and parent cycles before storing a task."""
        parent_id = task.parent_task_id
        if parent_id is None:
            return
        if parent_id == task.id:
            raise ValueError("Task cannot be its own parent")

        visited: set[str] = {task.id}
        current_id: str | None = parent_id
        while current_id is not None:
            if current_id in visited:
                raise ValueError("Cycle detected in parent_task_id chain")
            visited.add(current_id)
            current = self._tasks.get(current_id)
            if current is None:
                return
            current_id = current.parent_task_id

    def _propagate_parent(
        self, parent_id: str | None, visited: set[str] | None = None
    ) -> None:
        """Recalculate parent progress from children and auto-complete if all DONE (recursive)."""
        if parent_id is None:
            return
        if visited is None:
            visited = set()
        if parent_id in visited:
            return
        visited.add(parent_id)
        parent = self._tasks.get(parent_id)
        if parent is None:
            return
        children = [t for t in self._tasks.values() if t.parent_task_id == parent_id]
        if not children:
            return
        progress = sum(c.progress for c in children) / len(children)
        if all(c.status == TaskStatus.DONE for c in children):
            self._tasks[parent_id] = replace(
                parent,
                status=TaskStatus.DONE,
                completed_at=time.time(),
                progress=progress,
            )
        else:
            self._tasks[parent_id] = replace(parent, progress=progress)
        # Always recurse — progress changes even with partial completion
        self._propagate_parent(parent.parent_task_id, visited)

    def _collect_subtree_task_ids(self, task_id: str) -> set[str]:
        """BFS to collect task_id and all descendant task IDs."""
        result: set[str] = {task_id}
        queue = [task_id]
        visited: set[str] = set()
        while queue:
            tid = queue.pop(0)
            if tid in visited:
                continue
            visited.add(tid)
            for t in self._tasks.values():
                if t.parent_task_id == tid and t.id not in result:
                    result.add(t.id)
                    queue.append(t.id)
        return result
