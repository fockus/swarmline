"""ISP-compliant ports for coding task runtime.

Three protocols, each <=5 methods:
- CodingTaskLifecyclePort: create, start, complete, cancel, get_status (5)
- CodingTaskReadinessPort: is_ready, get_blockers, list_by_status (3)
- CodingTaskResumePort: save_snapshot, load_snapshot, list_snapshots, delete_snapshot (4)

Dependencies: only stdlib + sibling types module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.orchestration.coding_task_types import CodingTaskSnapshot, CodingTaskStatus


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

    async def list_by_status(self, status: CodingTaskStatus) -> list[CodingTaskSnapshot]: ...


@runtime_checkable
class CodingTaskResumePort(Protocol):
    """Snapshot persistence for restart/resume. ISP: 4 methods."""

    async def save_snapshot(self, snapshot: CodingTaskSnapshot) -> None: ...

    async def load_snapshot(self, task_id: str) -> CodingTaskSnapshot | None: ...

    async def list_snapshots(self, session_id: str) -> list[CodingTaskSnapshot]: ...

    async def delete_snapshot(self, task_id: str) -> bool: ...
