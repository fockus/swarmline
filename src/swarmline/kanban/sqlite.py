"""SQLite-backed kanban store — reference adapter (opt-in module).

Mirrors `multi_agent/graph_task_board_sqlite.py`: stdlib `sqlite3` +
`asyncio.to_thread` for non-blocking I/O, one connection per instance,
JSON-serialized task payloads, an explicit transaction per mutating call.
`kanban_tasks` holds the task rows; `kanban_task_links` is the multi-parent
`task_links` relation (mirrors `swarmline.kanban.types.TaskLink`).

Single-namespace (multi-tenant namespacing is taskloom's Postgres adapter,
a later task per the spec) — this is the storage-agnostic minimum.

`try_claim`/`release_claim`/`list_claimable` (`KanbanDispatch`) and
`append_note` (`KanbanNotes`) delegate to `sqlite_dispatch.py` — a sibling
module, so this file's pre-existing `KanbanStore`/`KanbanReadiness`/
`KanbanAssignment`/`KanbanRetitle` implementation stays untouched instead of
growing past the SRP line-count guideline for this additive increment.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from swarmline.kanban.sqlite_dispatch import (
    append_note_sync,
    list_claimable_sync,
    release_claim_sync,
    try_claim_sync,
)
from swarmline.kanban._time import now_iso as _now_iso
from swarmline.kanban.store import _BLOCK_ESCALATION_THRESHOLD
from swarmline.kanban.types import BlockKind, KanbanNote, KanbanStatus, KanbanTask


_DDL = """
CREATE TABLE IF NOT EXISTS kanban_tasks (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_task_links (
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id),
    FOREIGN KEY(parent_id) REFERENCES kanban_tasks(id),
    FOREIGN KEY(child_id) REFERENCES kanban_tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_kanban_links_parent ON kanban_task_links(parent_id);
CREATE INDEX IF NOT EXISTS idx_kanban_links_child ON kanban_task_links(child_id);
"""


def _serialize(task: KanbanTask) -> str:
    return json.dumps(
        {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "parent_ids": list(task.parent_ids),
            "block_kind": (
                task.block_kind.value if task.block_kind is not None else None
            ),
            "block_recurrences": task.block_recurrences,
            "metadata": task.metadata,
            "assignee": task.assignee,
            "claimed_at": task.claimed_at,
            "last_heartbeat_at": task.last_heartbeat_at,
        }
    )


def _deserialize(raw: str) -> KanbanTask:
    data = json.loads(raw)
    block_kind = data.get("block_kind")
    return KanbanTask(
        id=data["id"],
        title=data["title"],
        status=KanbanStatus(data["status"]),
        parent_ids=tuple(data.get("parent_ids", ())),
        block_kind=BlockKind(block_kind) if block_kind is not None else None,
        block_recurrences=data.get("block_recurrences", 0),
        metadata=data.get("metadata", {}),
        assignee=data.get("assignee"),
        claimed_at=data.get("claimed_at"),
        last_heartbeat_at=data.get("last_heartbeat_at"),
    )


def _apply_status(
    task: KanbanTask, status: KanbanStatus, block_kind: BlockKind | None
) -> KanbanTask:
    """Replace `task` with `status` applied, escalating a repeat block to `triage`."""
    if status != KanbanStatus.BLOCKED:
        return replace(task, status=status)
    recurrences = task.block_recurrences + 1
    escalate = recurrences > _BLOCK_ESCALATION_THRESHOLD
    return replace(
        task,
        status=KanbanStatus.TRIAGE if escalate else KanbanStatus.BLOCKED,
        block_kind=block_kind,
        block_recurrences=recurrences,
    )


class SqliteKanbanStore:
    """SQLite implementation of `KanbanStore` + `KanbanReadiness`."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.executescript(_DDL)
        self._conn.commit()

    # --- Sync helpers ---

    def _load_sync(self, task_id: str) -> KanbanTask | None:
        cur = self._conn.execute(
            "SELECT data FROM kanban_tasks WHERE id = ?", (task_id,)
        )
        row = cur.fetchone()
        return _deserialize(row[0]) if row else None

    def _children_sync(self, parent_id: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT child_id FROM kanban_task_links WHERE parent_id = ?", (parent_id,)
        )
        return [r[0] for r in cur.fetchall()]

    def _create_sync(self, task: KanbanTask) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO kanban_tasks (id, data) VALUES (?, ?)",
                    (task.id, _serialize(task)),
                )
            except sqlite3.IntegrityError:
                self._conn.rollback()
                raise ValueError(f"Task already exists: {task.id!r}") from None
            for parent_id in task.parent_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO kanban_task_links (parent_id, child_id) "
                    "VALUES (?, ?)",
                    (parent_id, task.id),
                )
            self._conn.commit()

    def _link_sync(self, parent_id: str, child_id: str) -> None:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                parent = self._load_sync(parent_id)
                child = self._load_sync(child_id)
                if parent is None:
                    raise ValueError(f"Unknown parent task: {parent_id!r}")
                if child is None:
                    raise ValueError(f"Unknown child task: {child_id!r}")
                if self._would_create_cycle_sync(parent_id, child_id):
                    raise ValueError(
                        f"Linking {parent_id!r} -> {child_id!r} would create a cycle"
                    )
                if parent_id not in child.parent_ids:
                    updated = replace(child, parent_ids=(*child.parent_ids, parent_id))
                    self._conn.execute(
                        "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                        (_serialize(updated), child_id),
                    )
                self._conn.execute(
                    "INSERT OR IGNORE INTO kanban_task_links (parent_id, child_id) "
                    "VALUES (?, ?)",
                    (parent_id, child_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _would_create_cycle_sync(self, parent_id: str, child_id: str) -> bool:
        if parent_id == child_id:
            return True
        visited: set[str] = set()
        stack = [parent_id]
        while stack:
            current = stack.pop()
            if current == child_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            current_task = self._load_sync(current)
            if current_task is None:
                continue
            stack.extend(current_task.parent_ids)
        return False

    def _set_status_sync(
        self, task_id: str, status: KanbanStatus, block_kind: BlockKind | None
    ) -> KanbanTask:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                task = self._load_sync(task_id)
                if task is None:
                    raise ValueError(f"Unknown task: {task_id!r}")
                updated = _apply_status(task, status, block_kind)
                self._conn.execute(
                    "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                    (_serialize(updated), task_id),
                )
                self._conn.commit()
                return updated
            except Exception:
                self._conn.rollback()
                raise

    def _list_sync(self, **filters: Any) -> list[KanbanTask]:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM kanban_tasks")
            tasks = [_deserialize(r[0]) for r in cur.fetchall()]
        if "status" in filters:
            tasks = [t for t in tasks if t.status == filters["status"]]
        return tasks

    def _subtree_sync(self, task_id: str) -> list[KanbanTask]:
        with self._lock:
            cur = self._conn.execute(
                """
                WITH RECURSIVE sub(id) AS (
                    SELECT child_id FROM kanban_task_links WHERE parent_id = ?
                    UNION
                    SELECT l.child_id
                    FROM kanban_task_links l
                    JOIN sub s ON l.parent_id = s.id
                )
                SELECT id FROM sub
                """,
                (task_id,),
            )
            child_ids = [r[0] for r in cur.fetchall()]
            if not child_ids:
                return []
            placeholders = ",".join("?" * len(child_ids))
            cur2 = self._conn.execute(
                f"SELECT data FROM kanban_tasks WHERE id IN ({placeholders})",
                child_ids,
            )
            return [_deserialize(r[0]) for r in cur2.fetchall()]

    def _recompute_ready_sync(self, task_id: str) -> list[str]:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                task = self._load_sync(task_id)
                if task is None:
                    self._conn.rollback()
                    return []
                child_ids = self._children_sync(task_id)
                if not child_ids:
                    self._conn.rollback()
                    return []
                children = [self._load_sync(c) for c in child_ids]
                if any(c is None for c in children) or not all(
                    c.status == KanbanStatus.DONE for c in children if c is not None
                ):
                    self._conn.rollback()
                    return []
                if task.status in (KanbanStatus.READY, KanbanStatus.DONE):
                    self._conn.rollback()
                    return []
                updated = replace(task, status=KanbanStatus.READY)
                self._conn.execute(
                    "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                    (_serialize(updated), task_id),
                )
                self._conn.commit()
                return [task_id]
            except Exception:
                self._conn.rollback()
                raise

    def _claim_sync(self, task_id: str, assignee: str) -> KanbanTask:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                task = self._load_sync(task_id)
                if task is None:
                    raise ValueError(f"Unknown task: {task_id!r}")
                now = _now_iso()
                updated = replace(
                    task, assignee=assignee, claimed_at=now, last_heartbeat_at=now
                )
                self._conn.execute(
                    "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                    (_serialize(updated), task_id),
                )
                self._conn.commit()
                return updated
            except Exception:
                self._conn.rollback()
                raise

    def _heartbeat_sync(self, task_id: str) -> KanbanTask:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                task = self._load_sync(task_id)
                if task is None:
                    raise ValueError(f"Unknown task: {task_id!r}")
                if task.assignee is None:
                    raise ValueError(f"Task {task_id!r} has never been claimed")
                updated = replace(task, last_heartbeat_at=_now_iso())
                self._conn.execute(
                    "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                    (_serialize(updated), task_id),
                )
                self._conn.commit()
                return updated
            except Exception:
                self._conn.rollback()
                raise

    def _update_title_sync(self, task_id: str, title: str) -> KanbanTask:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                task = self._load_sync(task_id)
                if task is None:
                    raise ValueError(f"Unknown task: {task_id!r}")
                updated = replace(task, title=title)
                self._conn.execute(
                    "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                    (_serialize(updated), task_id),
                )
                self._conn.commit()
                return updated
            except Exception:
                self._conn.rollback()
                raise

    # --- KanbanStore (async API) ---

    async def create_task(self, task: KanbanTask) -> None:
        await asyncio.to_thread(self._create_sync, task)

    async def link_tasks(self, parent_id: str, child_id: str) -> None:
        await asyncio.to_thread(self._link_sync, parent_id, child_id)

    async def set_status(
        self,
        task_id: str,
        status: KanbanStatus,
        *,
        block_kind: BlockKind | None = None,
    ) -> KanbanTask:
        return await asyncio.to_thread(
            self._set_status_sync, task_id, status, block_kind
        )

    async def list_tasks(self, **filters: Any) -> list[KanbanTask]:
        return await asyncio.to_thread(self._list_sync, **filters)

    async def get_subtree(self, task_id: str) -> list[KanbanTask]:
        return await asyncio.to_thread(self._subtree_sync, task_id)

    # --- KanbanReadiness ---

    async def recompute_ready(self, task_id: str) -> list[str]:
        return await asyncio.to_thread(self._recompute_ready_sync, task_id)

    # --- KanbanAssignment ---

    async def claim_task(self, task_id: str, assignee: str) -> KanbanTask:
        return await asyncio.to_thread(self._claim_sync, task_id, assignee)

    async def heartbeat(self, task_id: str) -> KanbanTask:
        return await asyncio.to_thread(self._heartbeat_sync, task_id)

    # --- KanbanRetitle ---

    async def update_title(self, task_id: str, title: str) -> KanbanTask:
        return await asyncio.to_thread(self._update_title_sync, task_id, title)

    # --- KanbanDispatch ---

    async def try_claim(
        self,
        task_id: str,
        assignee: str,
        *,
        lease_id: str,
        stale_before: str,
    ) -> KanbanTask | None:
        return await asyncio.to_thread(
            try_claim_sync,
            self._conn,
            self._lock,
            task_id,
            assignee,
            lease_id=lease_id,
            stale_before=stale_before,
        )

    async def release_claim(self, task_id: str, *, lease_id: str) -> KanbanTask:
        return await asyncio.to_thread(
            release_claim_sync, self._conn, self._lock, task_id, lease_id=lease_id
        )

    async def list_claimable(
        self,
        *,
        statuses: Sequence[KanbanStatus],
        stale_before: str,
        limit: int,
        include_fresh_claims: bool = False,
    ) -> list[KanbanTask]:
        return await asyncio.to_thread(
            list_claimable_sync,
            self._conn,
            self._lock,
            statuses=statuses,
            stale_before=stale_before,
            limit=limit,
            include_fresh_claims=include_fresh_claims,
        )

    # --- KanbanNotes ---

    async def append_note(
        self,
        task_id: str,
        note: KanbanNote,
        *,
        max_notes: int,
    ) -> KanbanTask:
        return await asyncio.to_thread(
            append_note_sync, self._conn, self._lock, task_id, note, max_notes=max_notes
        )

    # --- Convenience (not part of the KanbanStore protocol, ISP <=5) ---

    async def complete_task(self, task_id: str) -> KanbanTask:
        """Sugar for `set_status(task_id, KanbanStatus.DONE)`."""
        return await self.set_status(task_id, KanbanStatus.DONE)
