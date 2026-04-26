"""Shared agent registry and cross-namespace dependency resolver.

SharedAgentRegistry — agents (judge, reviewer) visible across all namespaced boards.
CrossNamespaceResolver — resolves task dependencies that cross namespace boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from swarmline.multi_agent.task_types import TaskStatus

if TYPE_CHECKING:
    from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
    from swarmline.multi_agent.graph_task_types import GraphTaskItem
    from swarmline.multi_agent.graph_types import AgentNode


class SharedAgentRegistry:
    """Registry for agents shared across multiple namespaced boards.

    Typical shared roles: judge, reviewer, security_auditor.
    These agents need visibility into all boards but are not owned by any single board.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentNode] = {}
        self._roles: dict[str, set[str]] = {}  # role -> set of agent_ids

    def register(
        self, agent: AgentNode, shared_roles: tuple[str, ...] | None = None
    ) -> None:
        """Register an agent as shared. Uses agent.role if shared_roles not provided."""
        self._agents[agent.id] = agent
        roles = shared_roles if shared_roles is not None else (agent.role,)
        for role in roles:
            self._roles.setdefault(role, set()).add(agent.id)

    def unregister(self, agent_id: str) -> None:
        """Remove agent from registry. No-op if not found."""
        self._agents.pop(agent_id, None)
        for role_set in self._roles.values():
            role_set.discard(agent_id)

    def get_shared_agents(self, role: str | None = None) -> list[AgentNode]:
        """Return shared agents, optionally filtered by role."""
        if role is not None:
            ids = self._roles.get(role, set())
            return [self._agents[aid] for aid in ids if aid in self._agents]
        return list(self._agents.values())

    def is_shared(self, agent_id: str) -> bool:
        """True if agent_id is registered as shared."""
        return agent_id in self._agents


class CrossNamespaceResolver:
    """Resolves task dependencies that cross namespace boundaries.

    Only used in unified execution mode where multiple goals share infrastructure.
    """

    def __init__(self, boards: dict[str, InMemoryGraphTaskBoard]) -> None:
        self._boards = boards

    async def resolve_task(self, task_id: str) -> tuple[str, GraphTaskItem] | None:
        """Search all boards for a task_id. Returns (namespace, task) or None."""
        for ns, board in self._boards.items():
            tasks = await board.list_tasks()
            for task in tasks:
                if task.id == task_id:
                    return (ns, task)
        return None

    async def get_blocked_by(self, task_id: str, namespace: str) -> list[GraphTaskItem]:
        """Return dependency tasks that are not yet DONE, searching across all namespaces."""
        board = self._boards.get(namespace)
        if board is None:
            return []
        tasks = await board.list_tasks()
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            return []
        if not task.dependencies:
            return []

        blockers: list[GraphTaskItem] = []
        for dep_id in task.dependencies:
            dep_result = await self.resolve_task(dep_id)
            if dep_result is not None:
                _, dep_task = dep_result
                if dep_task.status != TaskStatus.DONE:
                    blockers.append(dep_task)
        return blockers

    async def are_dependencies_met(self, task_id: str, namespace: str) -> bool:
        """True if all dependencies (local and cross-namespace) are DONE."""
        board = self._boards.get(namespace)
        if board is None:
            return True
        tasks = await board.list_tasks()
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            return True
        if not task.dependencies:
            return True

        for dep_id in task.dependencies:
            dep_result = await self.resolve_task(dep_id)
            if dep_result is None:
                return False  # dependency not found anywhere
            _, dep_task = dep_result
            if dep_task.status != TaskStatus.DONE:
                return False
        return True
