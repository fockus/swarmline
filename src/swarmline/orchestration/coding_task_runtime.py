"""DefaultCodingTaskRuntime — facade for coding task lifecycle on GraphTaskBoard.

Thin facade that delegates task state to GraphTaskBoard and snapshot
persistence to TaskSessionStore. Status mapping: CodingTaskStatus <-> TaskStatus.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.task_types import TaskStatus
from swarmline.orchestration.coding_task_types import (
    CodingTaskSnapshot,
    CodingTaskStatus,
    _CODING_TO_TASK,
    _TASK_TO_CODING,
)

if TYPE_CHECKING:
    from swarmline.protocols.graph_task import GraphTaskBoard
    from swarmline.session.task_session_store import TaskSessionStore


class DefaultCodingTaskRuntime:
    """Coding task runtime facade over GraphTaskBoard + TaskSessionStore.

    Implements CodingTaskLifecyclePort, CodingTaskReadinessPort,
    and CodingTaskResumePort.

    Delegates to:
    - GraphTaskBoard for task state management (lifecycle, readiness)
    - TaskSessionStore for snapshot persistence (resume)

    Note: GraphTaskBoard does not expose get_task(id), so _find_task uses
    list_tasks() with O(n) scan. Acceptable for typical coding session
    task counts (< 100). If scaling is needed, add get_task to the protocol.
    """

    def __init__(
        self,
        board: GraphTaskBoard,
        session_store: TaskSessionStore,
        *,
        namespace: str = "coding",
    ) -> None:
        if board is None:
            raise ValueError("board is required for DefaultCodingTaskRuntime")
        if session_store is None:
            raise ValueError("session_store is required for DefaultCodingTaskRuntime")
        self._board = board
        self._session_store = session_store
        self._namespace = namespace

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_task(self, task_id: str) -> GraphTaskItem | None:
        """Find a task by ID on the board. Returns None if not found."""
        tasks = await self._board.list_tasks()
        return next((t for t in tasks if t.id == task_id), None)

    def _map_status(self, task_status: TaskStatus) -> CodingTaskStatus:
        """Map GraphTaskBoard TaskStatus to CodingTaskStatus."""
        return CodingTaskStatus(_TASK_TO_CODING[task_status.value])

    async def _persist_snapshot(self, snapshot: CodingTaskSnapshot) -> None:
        """Save a snapshot through the session store."""
        await self._session_store.save(
            self._namespace, snapshot.task_id, snapshot.to_dict(),
        )

    async def _build_snapshot(
        self,
        task_id: str,
        status: CodingTaskStatus,
        *,
        title: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> CodingTaskSnapshot:
        """Build a snapshot, inheriting fields from existing snapshot if available."""
        existing = await self.load_snapshot(task_id)
        now = time.time()
        return CodingTaskSnapshot(
            task_id=task_id,
            status=status,
            session_id=session_id or (existing.session_id if existing else ""),
            title=title or (existing.title if existing else ""),
            created_at=created_at or (existing.created_at if existing else now),
            updated_at=now,
            metadata=MappingProxyType(
                dict(metadata) if metadata is not None else (
                    dict(existing.metadata) if existing else {}
                ),
            ),
        )

    # ------------------------------------------------------------------
    # CodingTaskLifecyclePort (5 methods)
    # ------------------------------------------------------------------

    async def create_task(
        self,
        task_id: str,
        title: str,
        *,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CodingTaskSnapshot:
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be non-empty")
        item = GraphTaskItem(id=task_id, title=title, status=TaskStatus.TODO)
        await self._board.create_task(item)

        now = time.time()
        snap = CodingTaskSnapshot(
            task_id=task_id,
            status=CodingTaskStatus.PENDING,
            session_id=session_id,
            title=title,
            created_at=now,
            updated_at=now,
            metadata=MappingProxyType(metadata or {}),
        )
        await self._persist_snapshot(snap)
        return snap

    async def start_task(self, task_id: str, agent_id: str) -> CodingTaskSnapshot:
        result = await self._board.checkout_task(task_id, agent_id)
        if result is None:
            task = await self._find_task(task_id)
            if task is None:
                raise LookupError(f"Task '{task_id}' not found")
            raise ValueError(
                f"Cannot start task '{task_id}' in status {task.status.value}"
            )

        snap = await self._build_snapshot(task_id, CodingTaskStatus.ACTIVE)
        await self._persist_snapshot(snap)
        return snap

    async def complete_task(self, task_id: str) -> CodingTaskSnapshot:
        task = await self._find_task(task_id)
        if task is None:
            raise LookupError(f"Task '{task_id}' not found")

        ok = await self._board.complete_task(task_id)
        if not ok:
            raise ValueError(
                f"Cannot complete task '{task_id}' in status {task.status.value}"
            )

        snap = await self._build_snapshot(task_id, CodingTaskStatus.COMPLETED)
        await self._persist_snapshot(snap)
        return snap

    async def cancel_task(self, task_id: str) -> bool:
        ok = await self._board.cancel_task(task_id)
        if ok:
            snap = await self._build_snapshot(task_id, CodingTaskStatus.CANCELLED)
            await self._persist_snapshot(snap)
        return ok

    async def get_status(self, task_id: str) -> CodingTaskStatus | None:
        task = await self._find_task(task_id)
        if task is None:
            return None
        return self._map_status(task.status)

    # ------------------------------------------------------------------
    # CodingTaskReadinessPort (3 methods)
    # ------------------------------------------------------------------

    async def is_ready(self, task_id: str) -> bool:
        ready = await self._board.get_ready_tasks()
        return any(t.id == task_id for t in ready)

    async def get_blockers(self, task_id: str) -> list[str]:
        blockers = await self._board.get_blocked_by(task_id)
        return [b.id for b in blockers]

    async def list_by_status(
        self, status: CodingTaskStatus,
    ) -> list[CodingTaskSnapshot]:
        task_status_val = _CODING_TO_TASK[status.value]
        task_status = TaskStatus(task_status_val)
        tasks = await self._board.list_tasks(status=task_status)
        snapshots: list[CodingTaskSnapshot] = []
        for task in tasks:
            loaded = await self.load_snapshot(task.id)
            if loaded is not None:
                snapshots.append(loaded)
            else:
                snapshots.append(
                    CodingTaskSnapshot(
                        task_id=task.id,
                        status=status,
                        session_id="",
                        title=task.title,
                        created_at=task.created_at,
                        updated_at=task.updated_at,
                    )
                )
        return snapshots

    # ------------------------------------------------------------------
    # CodingTaskResumePort (4 methods)
    # ------------------------------------------------------------------

    async def save_snapshot(self, snapshot: CodingTaskSnapshot) -> None:
        await self._persist_snapshot(snapshot)

    async def load_snapshot(self, task_id: str) -> CodingTaskSnapshot | None:
        data = await self._session_store.load(self._namespace, task_id)
        if data is None:
            return None
        return CodingTaskSnapshot.from_dict(data)

    async def list_snapshots(self, session_id: str) -> list[CodingTaskSnapshot]:
        entries = await self._session_store.list_by_agent(self._namespace)
        results: list[CodingTaskSnapshot] = []
        for entry in entries:
            snap = CodingTaskSnapshot.from_dict(entry.params)
            if snap.session_id == session_id:
                results.append(snap)
        return results

    async def delete_snapshot(self, task_id: str) -> bool:
        return await self._session_store.delete(self._namespace, task_id)
