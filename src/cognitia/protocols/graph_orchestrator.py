"""Graph orchestrator protocols — hierarchical agent execution engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cognitia.multi_agent.graph_orchestrator_types import (
        DelegationRequest,
        OrchestratorRunStatus,
    )


@runtime_checkable
class GraphOrchestrator(Protocol):
    """Hierarchical multi-agent execution engine. ISP: 5 methods.

    Flow: start(goal) → root decomposes → delegate subtasks
    → agents run in parallel → results bubble up.
    """

    async def start(self, goal: str) -> str:
        """Start a new orchestration run.  Returns run_id."""
        ...

    async def delegate(self, request: DelegationRequest) -> None:
        """Delegate a task to a specific agent."""
        ...

    async def collect_result(self, task_id: str) -> str | None:
        """Collect the result for a completed task (None if not done)."""
        ...

    async def get_status(self, run_id: str) -> OrchestratorRunStatus:
        """Get the current status of an orchestration run."""
        ...

    async def stop(self, run_id: str) -> None:
        """Stop an orchestration run gracefully."""
        ...


@runtime_checkable
class GraphTaskWaiter(Protocol):
    """Wait for task completion. ISP: 1 method.

    Separated from GraphOrchestrator to keep ISP <=5.
    Implementations should implement both protocols.
    """

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> str | None:
        """Wait for a task to complete. Returns result or None on timeout."""
        ...


@runtime_checkable
class PersistentOrchestrator(Protocol):
    """Persistent agent graph with goal queue. ISP: 5 methods."""

    async def submit_goal(self, goal: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Submit a goal. Returns goal_id."""
        ...

    def get_goal_queue(self) -> list[Any]:
        """Return all goals."""
        ...

    async def add_agent(self, node: Any) -> None:
        """Add agent to structure."""
        ...

    async def remove_agent(self, agent_id: str) -> None:
        """Remove agent from structure."""
        ...

    async def shutdown(self) -> None:
        """Shutdown all agents."""
        ...
