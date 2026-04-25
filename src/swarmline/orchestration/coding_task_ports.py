"""ISP-compliant ports for coding task runtime.

Three narrow ports (each ≤5 methods, strictly ISP-compliant):
- CodingTaskLifecyclePort: create, start, complete, cancel, get_status (5)
- CodingTaskReadinessPort: is_ready, get_blockers, list_by_status (3)
- CodingTaskResumePort: save_snapshot, load_snapshot, list_snapshots, delete_snapshot (4)

Plus one *composition* port (architectural composition of GraphTaskBoard +
GraphTaskScheduler + backend cancel_task — see CodingTaskBoardPort docstring):
- CodingTaskBoardPort: 7 methods, used as the `board` dependency hint for
  DefaultCodingTaskRuntime. Underlying source protocols (`GraphTaskBoard`,
  `GraphTaskScheduler`) stay narrow in swarmline.protocols.graph_task — this
  port aggregates their surface for the runtime's single-parameter API.

Backends (InMemoryGraphTaskBoard, SqliteGraphTaskBoard, PostgresGraphTaskBoard)
satisfy the composition via duck typing.

Dependencies: only stdlib + sibling types module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.multi_agent.graph_task_types import GraphTaskItem
    from swarmline.orchestration.coding_task_types import (
        CodingTaskSnapshot,
        CodingTaskStatus,
    )


@runtime_checkable
class CodingTaskLifecyclePort(Protocol):
    """Task lifecycle management backed by GraphTaskBoard. ISP: 5 methods.

    create_task / start_task / complete_task always return a snapshot.
    start_task raises LookupError if task not found, ValueError if wrong status.
    complete_task raises LookupError if task not found, ValueError if wrong status.
    cancel_task returns bool (True if cancelled, False otherwise).
    get_status returns None if task not found.
    """

    async def create_task(
        self,
        task_id: str,
        title: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CodingTaskSnapshot: ...

    async def start_task(self, task_id: str, agent_id: str) -> CodingTaskSnapshot: ...

    async def complete_task(self, task_id: str) -> CodingTaskSnapshot: ...

    async def cancel_task(self, task_id: str) -> bool: ...

    async def get_status(self, task_id: str) -> CodingTaskStatus | None: ...


@runtime_checkable
class CodingTaskReadinessPort(Protocol):
    """Task readiness checking and filtering. ISP: 3 methods."""

    async def is_ready(self, task_id: str) -> bool: ...

    async def get_blockers(self, task_id: str) -> list[str]: ...

    async def list_by_status(
        self, status: CodingTaskStatus
    ) -> list[CodingTaskSnapshot]: ...


@runtime_checkable
class CodingTaskResumePort(Protocol):
    """Snapshot persistence for restart/resume. ISP: 4 methods."""

    async def save_snapshot(self, snapshot: CodingTaskSnapshot) -> None: ...

    async def load_snapshot(self, task_id: str) -> CodingTaskSnapshot | None: ...

    async def list_snapshots(self, session_id: str) -> list[CodingTaskSnapshot]: ...

    async def delete_snapshot(self, task_id: str) -> bool: ...


@runtime_checkable
class CodingTaskBoardPort(Protocol):
    """Composed board dependency for DefaultCodingTaskRuntime.

    Surface = exactly the methods the runtime calls on its board:
    - GraphTaskBoard methods: create_task, checkout_task, complete_task, list_tasks
    - GraphTaskScheduler methods: get_ready_tasks, get_blocked_by
    - Backend-specific: cancel_task

    Total: 7 methods. Architecturally this is a *composition* of three narrow
    protocols (each ≤5 methods, ISP-compliant). All concrete backends
    (InMemoryGraphTaskBoard, SqliteGraphTaskBoard, PostgresGraphTaskBoard)
    natively implement every method.

    Note: duplicating the signatures here (rather than inheriting from
    GraphTaskBoard / GraphTaskScheduler) avoids a circular protocols ↔
    orchestration import edge while keeping `ty` strict happy. This Port lives
    in the orchestration layer; the canonical narrow protocols stay in
    swarmline.protocols.graph_task and remain the source of truth for backend
    compatibility tests.

    Replaces the narrow GraphTaskBoard hint that triggered 3 unresolved-
    attribute errors at lines 163/180/184 (now 165/182/186 post-format) prior
    to Sprint 1A Stage 2.
    """

    async def create_task(self, task: GraphTaskItem) -> None: ...

    async def checkout_task(
        self, task_id: str, agent_id: str
    ) -> GraphTaskItem | None: ...

    async def complete_task(self, task_id: str) -> bool: ...

    async def cancel_task(self, task_id: str) -> bool: ...

    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]: ...

    async def get_ready_tasks(self) -> list[GraphTaskItem]: ...

    async def get_blocked_by(self, task_id: str) -> list[GraphTaskItem]: ...
