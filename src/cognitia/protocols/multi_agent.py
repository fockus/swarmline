"""Multi-agent protocols -- agent-as-tool, task queue, and agent registry contracts.

ISP-compliant: AgentTool has 1 method, TaskQueue has 5 methods, AgentRegistry has 5 methods.
Dependencies: cognitia domain types and stdlib only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from cognitia.multi_agent.task_types import TaskFilter, TaskItem

if TYPE_CHECKING:
    from cognitia.domain_types import ToolSpec
    from cognitia.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus


@runtime_checkable
class AgentTool(Protocol):
    """Port: agent exposable as a tool for other agents.

    Any runtime or agent wrapper implementing this Protocol
    can be used as a sub-agent tool in another agent's tool list.
    """

    def as_tool(self, name: str, description: str) -> ToolSpec: ...


@runtime_checkable
class TaskQueue(Protocol):
    """Async task queue for multi-agent coordination.

    Exactly 5 methods (ISP limit). All methods are async.
    """

    async def put(self, item: TaskItem) -> None:
        """Add a task to the queue."""
        ...

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        """Claim the highest-priority TODO task matching filters.

        Implementations must return the claimed task in IN_PROGRESS status.
        Returns None if no matching task is available.
        """
        ...

    async def complete(self, task_id: str) -> bool:
        """Mark a task as done. Returns True if found and completed."""
        ...

    async def cancel(self, task_id: str) -> bool:
        """Mark a task as cancelled. Returns True if found and cancelled."""
        ...

    async def list_tasks(
        self, filters: TaskFilter | None = None
    ) -> list[TaskItem]:
        """List all tasks matching filters. Returns all if filters is None."""
        ...


@runtime_checkable
class AgentRegistry(Protocol):
    """Port: registry for managing agent lifecycle records.

    Provides CRUD operations for AgentRecord instances with
    filtering support. Exactly 5 methods (ISP limit).
    """

    async def register(self, record: AgentRecord) -> None: ...

    async def get(self, agent_id: str) -> AgentRecord | None: ...

    async def list_agents(
        self, filters: AgentFilter | None = None,
    ) -> list[AgentRecord]: ...

    async def update_status(self, agent_id: str, status: AgentStatus) -> bool: ...

    async def remove(self, agent_id: str) -> bool: ...
