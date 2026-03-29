"""In-memory hierarchical task board with atomic checkout and status propagation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from cognitia.multi_agent.graph_task_types import GoalAncestry, GraphTaskItem, TaskComment
from cognitia.multi_agent.task_types import TaskStatus


class InMemoryGraphTaskBoard:
    """In-memory implementation of GraphTaskBoard + TaskCommentStore."""

    def __init__(self) -> None:
        self._tasks: dict[str, GraphTaskItem] = {}
        self._comments: list[TaskComment] = []
        self._lock = asyncio.Lock()

    # --- GraphTaskBoard (5 methods) ---

    async def create_task(self, task: GraphTaskItem) -> None:
        async with self._lock:
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
            )
            self._tasks[task_id] = updated
            return updated

    async def complete_task(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            self._tasks[task_id] = replace(task, status=TaskStatus.DONE)
            # Auto-propagate: check if parent's subtasks are all done
            self._propagate_completion(task.parent_task_id)
            return True

    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]:
        return [t for t in self._tasks.values() if t.parent_task_id == task_id]

    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]:
        result = list(self._tasks.values())
        if "status" in filters:
            result = [t for t in result if t.status == filters["status"]]
        if "assignee_agent_id" in filters:
            result = [t for t in result if t.assignee_agent_id == filters["assignee_agent_id"]]
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
        task_ids = self._collect_subtree_task_ids(task_id)
        return [c for c in self._comments if c.task_id in task_ids]

    # --- Extra: GoalAncestry ---

    async def get_goal_ancestry(self, task_id: str) -> GoalAncestry | None:
        """Walk parent_task_id chain to build goal ancestry."""
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

    def _propagate_completion(self, parent_id: str | None) -> None:
        """If all subtasks of parent are DONE, auto-complete parent (recursive)."""
        if parent_id is None:
            return
        parent = self._tasks.get(parent_id)
        if parent is None:
            return
        subtasks = [t for t in self._tasks.values() if t.parent_task_id == parent_id]
        if not subtasks:
            return
        if all(t.status == TaskStatus.DONE for t in subtasks):
            self._tasks[parent_id] = replace(parent, status=TaskStatus.DONE)
            self._propagate_completion(parent.parent_task_id)

    def _collect_subtree_task_ids(self, task_id: str) -> set[str]:
        """BFS to collect task_id and all descendant task IDs."""
        result: set[str] = {task_id}
        queue = [task_id]
        while queue:
            tid = queue.pop(0)
            for t in self._tasks.values():
                if t.parent_task_id == tid and t.id not in result:
                    result.add(t.id)
                    queue.append(t.id)
        return result
