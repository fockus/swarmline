"""RoutineBridge — bridges daemon.Scheduler with multi_agent.GraphTaskBoard.

Registers routines that auto-create tasks on a schedule with dedup logic.
"""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

import structlog

from swarmline.daemon.routine_types import Routine, RoutineRun, RunStatus
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.task_types import TaskStatus

logger = structlog.get_logger(component="daemon.routine_bridge")


@runtime_checkable
class RoutineManager(Protocol):
    """Scheduler -> TaskBoard bridge. ISP: 4 methods."""

    async def register(self, routine: Routine) -> str: ...
    async def unregister(self, routine_id: str) -> bool: ...
    async def list_routines(self) -> list[Routine]: ...
    async def get_runs(self, routine_id: str) -> list[RoutineRun]: ...


class RoutineBridge:
    """Concrete bridge: registers routines in a TaskScheduler that auto-create
    GraphTaskItems on a GraphTaskBoard.

    Constructor accepts protocol-typed dependencies (TaskScheduler, GraphTaskBoard).
    Optional event_bus for emitting ``daemon.routine.triggered`` events.
    """

    def __init__(
        self,
        scheduler: Any,  # TaskScheduler protocol
        task_board: Any,  # GraphTaskBoard protocol
        *,
        event_bus: Any | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._task_board = task_board
        self._event_bus = event_bus
        self._routines: dict[str, Routine] = {}
        self._runs: list[RoutineRun] = []

    async def register(self, routine: Routine) -> str:
        """Register a routine: store it and schedule periodic trigger.

        Returns the routine ID.
        """
        self._routines[routine.id] = routine
        trigger = self._make_trigger(routine)
        self._scheduler.every(
            routine.interval_seconds,
            trigger,
            name=f"routine:{routine.id}",
        )
        logger.info(
            "routine.registered",
            routine_id=routine.id,
            name=routine.name,
            interval=routine.interval_seconds,
        )
        return routine.id

    async def unregister(self, routine_id: str) -> bool:
        """Unregister a routine: cancel scheduler task and remove.

        Returns True if found, False if not.
        """
        if routine_id not in self._routines:
            return False
        self._scheduler.cancel(f"routine:{routine_id}")
        del self._routines[routine_id]
        logger.info("routine.unregistered", routine_id=routine_id)
        return True

    async def list_routines(self) -> list[Routine]:
        """List all currently registered routines."""
        return list(self._routines.values())

    async def get_runs(self, routine_id: str) -> list[RoutineRun]:
        """Get run history for a routine."""
        return [r for r in self._runs if r.routine_id == routine_id]

    def _make_trigger(self, routine: Routine) -> Callable[[], Awaitable[None]]:
        """Create an async callable that the scheduler will invoke periodically.

        The trigger checks dedup, creates a task on the board, and records
        the run outcome.
        """

        async def _trigger() -> None:
            # Dedup check: if dedup_key is set, look for open tasks
            if routine.dedup_key:
                existing_tasks = await self._task_board.list_tasks()
                open_statuses = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
                has_open = any(
                    t.metadata.get("dedup_key") == routine.dedup_key
                    and t.status in open_statuses
                    for t in existing_tasks
                )
                if has_open:
                    run = RoutineRun(
                        routine_id=routine.id,
                        task_id=None,
                        status=RunStatus.SKIPPED_DEDUP,
                        reason=f"Open task with dedup_key={routine.dedup_key!r} exists",
                    )
                    self._runs.append(run)
                    logger.debug(
                        "routine.skipped_dedup",
                        routine_id=routine.id,
                        dedup_key=routine.dedup_key,
                    )
                    return

            # Create task
            task_id = f"routine-{routine.id}-{uuid.uuid4().hex[:8]}"
            task = GraphTaskItem(
                id=task_id,
                title=routine.goal_template,
                assignee_agent_id=routine.agent_id,
                metadata={
                    "routine_id": routine.id,
                    "dedup_key": routine.dedup_key,
                },
            )
            await self._task_board.create_task(task)

            run = RoutineRun(
                routine_id=routine.id,
                task_id=task_id,
                status=RunStatus.CREATED,
            )
            self._runs.append(run)

            logger.info(
                "routine.triggered",
                routine_id=routine.id,
                task_id=task_id,
            )

            # Emit event if event_bus is available
            if self._event_bus is not None:
                await self._event_bus.emit(
                    "daemon.routine.triggered",
                    {
                        "routine_id": routine.id,
                        "task_id": task_id,
                        "routine_name": routine.name,
                    },
                )

        return _trigger
