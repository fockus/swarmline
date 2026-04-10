"""PersistentGraphOrchestrator — org-like structure with continuous goal processing."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from cognitia.multi_agent.goal_queue import GoalEntry, GoalQueue
from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
from cognitia.multi_agent.graph_types import AgentNode

_log = structlog.get_logger(component="persistent_graph")


class PersistentGraphOrchestrator:
    """Extends DefaultGraphOrchestrator with persistent structure and goal queue.

    Agents in PERSISTENT mode stay alive across goals.
    Goals are queued and processed sequentially.
    Only orchestrator can add/remove agents.
    """

    def __init__(
        self,
        graph: Any,
        task_board: Any,
        agent_runner: Any,
        *,
        event_bus: Any | None = None,
        max_concurrent: int = 5,
        auto_process: bool = True,
    ) -> None:
        self._graph = graph
        self._orchestrator = DefaultGraphOrchestrator(
            graph=graph,
            task_board=task_board,
            agent_runner=agent_runner,
            event_bus=event_bus,
            max_concurrent=max_concurrent,
        )
        self._goal_queue = GoalQueue()
        self._bus = event_bus
        self._auto_process = auto_process
        self._processing = False
        self._current_goal: GoalEntry | None = None
        self._process_task: asyncio.Task[None] | None = None

    async def submit_goal(self, goal: str, *, metadata: dict[str, Any] | None = None) -> str:
        """Submit a goal to the persistent graph. Returns goal_id."""
        entry = self._goal_queue.submit(goal, metadata=metadata)
        _log.info("goal_submitted", goal_id=entry.id, goal=goal)

        if self._bus is not None:
            await self._bus.emit("persistent.goal.submitted", {"goal_id": entry.id, "goal": goal})

        # Auto-start processing if idle
        if self._auto_process and not self._processing:
            self._process_task = asyncio.create_task(self._process_loop())

        return entry.id

    def get_goal_queue(self) -> list[GoalEntry]:
        """Return all goals (pending + completed)."""
        return self._goal_queue.list_all()

    def get_pending_goals(self) -> list[GoalEntry]:
        """Return pending goals."""
        return self._goal_queue.list_pending()

    async def add_agent(self, node: AgentNode) -> None:
        """Add an agent to the persistent structure."""
        await self._graph.add_node(node)
        _log.info("agent_added", agent_id=node.id, role=node.role)

    async def remove_agent(self, agent_id: str) -> None:
        """Remove an agent from the persistent structure."""
        if hasattr(self._graph, "remove_node"):
            await self._graph.remove_node(agent_id)
        _log.info("agent_removed", agent_id=agent_id)

    async def shutdown(self) -> None:
        """Gracefully shut down all persistent agents and stop processing."""
        self._processing = False
        if self._process_task and not self._process_task.done():
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        # Stop any active orchestration run
        if self._current_goal and self._current_goal.run_id:
            try:
                await self._orchestrator.stop(self._current_goal.run_id)
            except (KeyError, Exception):  # noqa: BLE001
                pass

        _log.info("persistent_graph_shutdown")

    async def _process_loop(self) -> None:
        """Process goals from the queue sequentially."""
        self._processing = True
        try:
            while self._processing:
                entry = self._goal_queue.dequeue()
                if entry is None:
                    break  # no more goals

                self._current_goal = entry
                _log.info("goal_processing", goal_id=entry.id, goal=entry.goal)

                try:
                    run_id = await self._orchestrator.start(entry.goal)
                    # Wait for completion
                    status = await self._orchestrator.get_status(run_id)
                    if status.root_task_id:
                        await self._orchestrator.wait_for_task(status.root_task_id)

                    self._goal_queue.mark_complete(entry.id, run_id=run_id)
                    _log.info("goal_completed", goal_id=entry.id, run_id=run_id)

                    if self._bus is not None:
                        await self._bus.emit("persistent.goal.completed", {
                            "goal_id": entry.id, "run_id": run_id,
                        })

                except Exception as exc:  # noqa: BLE001
                    self._goal_queue.mark_failed(entry.id)
                    _log.error("goal_failed", goal_id=entry.id, error=str(exc))

                    if self._bus is not None:
                        await self._bus.emit("persistent.goal.failed", {
                            "goal_id": entry.id, "error": str(exc),
                        })

                self._current_goal = None

        finally:
            self._processing = False
