"""Graph task board protocols — hierarchical tasks with atomic checkout."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cognitia.multi_agent.graph_task_types import GraphTaskItem, TaskComment


@runtime_checkable
class GraphTaskBoard(Protocol):
    """Hierarchical task management with atomic checkout. ISP: 5 methods."""

    async def create_task(self, task: GraphTaskItem) -> None: ...
    async def checkout_task(self, task_id: str, agent_id: str) -> GraphTaskItem | None: ...
    async def complete_task(self, task_id: str) -> bool: ...
    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]: ...
    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]: ...


@runtime_checkable
class TaskCommentStore(Protocol):
    """Persistent comment threads on tasks. ISP: 3 methods."""

    async def add_comment(self, comment: TaskComment) -> None: ...
    async def get_comments(self, task_id: str) -> list[TaskComment]: ...
    async def get_thread(self, task_id: str) -> list[TaskComment]: ...
