"""TaskQueue implementations (Phase 9B-MVP).

Two backends:
- InMemoryTaskQueue — default, zero dependencies.
- SqliteTaskQueue — file-based persistence via asyncio.to_thread().

Both implement the TaskQueue Protocol (protocols.multi_agent).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import asdict, replace
from typing import Final

from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)

_PRIORITY_ORDER: Final[dict[TaskPriority, int]] = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}

_TERMINAL: Final[frozenset[TaskStatus]] = frozenset(
    {TaskStatus.DONE, TaskStatus.CANCELLED}
)


def _matches(item: TaskItem, filters: TaskFilter | None) -> bool:
    if filters is None:
        return True
    if filters.status is not None and item.status != filters.status:
        return False
    if filters.priority is not None and item.priority != filters.priority:
        return False
    if (
        filters.assignee_agent_id is not None
        and item.assignee_agent_id != filters.assignee_agent_id
    ):
        return False
    return True


def _matches_get(item: TaskItem, filters: TaskFilter | None) -> bool:
    if item.status is not TaskStatus.TODO:
        return False
    if (
        filters is not None
        and filters.status is not None
        and filters.status is not TaskStatus.TODO
    ):
        return False
    if (
        filters is not None
        and filters.priority is not None
        and item.priority != filters.priority
    ):
        return False
    if filters is None or filters.assignee_agent_id is None:
        return item.assignee_agent_id is None
    return item.assignee_agent_id == filters.assignee_agent_id


def _pick_best(items: list[TaskItem]) -> TaskItem | None:
    if not items:
        return None
    return min(items, key=lambda t: _PRIORITY_ORDER[t.priority])


# ---------------------------------------------------------------------------
# InMemoryTaskQueue
# ---------------------------------------------------------------------------


class InMemoryTaskQueue:
    """In-memory task queue. Thread-safe via asyncio.Lock."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskItem] = {}
        self._lock = asyncio.Lock()

    async def put(self, item: TaskItem) -> None:
        async with self._lock:
            self._tasks[item.id] = item

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        async with self._lock:
            candidates = [t for t in self._tasks.values() if _matches_get(t, filters)]
            claimed = _pick_best(candidates)
            if claimed is None:
                return None
            claimed = replace(claimed, status=TaskStatus.IN_PROGRESS)
            self._tasks[claimed.id] = claimed
            return claimed

    async def complete(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in _TERMINAL:
                return False
            self._tasks[task_id] = replace(task, status=TaskStatus.DONE)
            return True

    async def cancel(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in _TERMINAL:
                return False
            self._tasks[task_id] = replace(task, status=TaskStatus.CANCELLED)
            return True

    async def list_tasks(
        self,
        filters: TaskFilter | None = None,
    ) -> list[TaskItem]:
        async with self._lock:
            return [t for t in self._tasks.values() if _matches(t, filters)]


# ---------------------------------------------------------------------------
# SqliteTaskQueue
# ---------------------------------------------------------------------------


def _item_to_json(item: TaskItem) -> str:
    d = asdict(item)
    d["status"] = item.status.value
    d["priority"] = item.priority.value
    return json.dumps(d, ensure_ascii=False)


def _item_from_json(raw: str) -> TaskItem:
    d = json.loads(raw)
    d["status"] = TaskStatus(d["status"])
    d["priority"] = TaskPriority(d["priority"])
    return TaskItem(**d)


class SqliteTaskQueue:
    """SQLite-backed task queue. Uses asyncio.to_thread() for I/O."""

    def __init__(self, db_path: str = "swarmline_tasks.db") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status "
            "ON tasks(json_extract(data, '$.status'))"
        )
        self._conn.commit()

    # -- sync helpers -------------------------------------------------------

    def _put_sync(self, task_id: str, data: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tasks (id, data) VALUES (?, ?)",
                (task_id, data),
            )
            self._conn.commit()

    def _get_all_sync(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM tasks")
            return [row[0] for row in cur.fetchall()]

    def _get_one_sync(self, task_id: str) -> str | None:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            return row[0] if row else None

    def _claim_one_sync(self, filters: TaskFilter | None) -> str | None:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")

                # Build SQL-level filter to avoid full-table scan
                assignee = filters.assignee_agent_id if filters is not None else None
                priority_value = (
                    filters.priority.value
                    if filters is not None and filters.priority is not None
                    else None
                )

                if assignee is not None:
                    # Fetch tasks assigned to a specific agent
                    sql = """
                        SELECT data FROM tasks
                        WHERE json_extract(data, '$.status') = 'todo'
                          AND json_extract(data, '$.assignee_agent_id') = ?
                    """
                    params: tuple = (assignee,)
                    if priority_value is not None:
                        sql += " AND json_extract(data, '$.priority') = ?"
                        params = (assignee, priority_value)
                else:
                    # No assignee filter: only pick unassigned tasks
                    sql = """
                        SELECT data FROM tasks
                        WHERE json_extract(data, '$.status') = 'todo'
                          AND json_extract(data, '$.assignee_agent_id') IS NULL
                    """
                    params = ()
                    if priority_value is not None:
                        sql += " AND json_extract(data, '$.priority') = ?"
                        params = (priority_value,)

                sql += """
                    ORDER BY
                      CASE json_extract(data, '$.priority')
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                      END
                    LIMIT 1
                """

                cur = self._conn.execute(sql, params)
                row = cur.fetchone()
                if row is None:
                    self._conn.commit()
                    return None

                claimed = replace(
                    _item_from_json(row[0]),
                    status=TaskStatus.IN_PROGRESS,
                )
                self._conn.execute(
                    "UPDATE tasks SET data = ? WHERE id = ?",
                    (_item_to_json(claimed), claimed.id),
                )
                self._conn.commit()
                return _item_to_json(claimed)
            except Exception:
                self._conn.rollback()
                raise

    def _transition_sync(self, task_id: str, target_status: TaskStatus) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "SELECT data FROM tasks WHERE id = ?",
                    (task_id,),
                )
                row = cur.fetchone()
                if row is None:
                    self._conn.commit()
                    return False

                task = _item_from_json(row[0])
                if task.status in _TERMINAL:
                    self._conn.commit()
                    return False

                updated = replace(task, status=target_status)
                self._conn.execute(
                    "UPDATE tasks SET data = ? WHERE id = ?",
                    (_item_to_json(updated), task_id),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    # -- async API ----------------------------------------------------------

    async def put(self, item: TaskItem) -> None:
        data = _item_to_json(item)
        await asyncio.to_thread(self._put_sync, item.id, data)

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        raw = await asyncio.to_thread(self._claim_one_sync, filters)
        if raw is None:
            return None
        return _item_from_json(raw)

    async def complete(self, task_id: str) -> bool:
        return await asyncio.to_thread(
            self._transition_sync,
            task_id,
            TaskStatus.DONE,
        )

    async def cancel(self, task_id: str) -> bool:
        return await asyncio.to_thread(
            self._transition_sync,
            task_id,
            TaskStatus.CANCELLED,
        )

    async def list_tasks(
        self,
        filters: TaskFilter | None = None,
    ) -> list[TaskItem]:
        rows = await asyncio.to_thread(self._get_all_sync)
        items = [_item_from_json(r) for r in rows]
        return [t for t in items if _matches(t, filters)]

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()
