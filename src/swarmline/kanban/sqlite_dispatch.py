"""SQLite CAS-safe dispatch (`KanbanDispatch`) + notes journal (`KanbanNotes`)
for `SqliteKanbanStore` — sibling module to `sqlite.py`.

Long-task-kanban-continuation increment (Sprint 1a, AGR-012/AGR-017,
REQ-LTK-009..015). Kept as a separate module — rather than growing
`sqlite.py` past the SRP line-count guideline — so the pre-existing
`KanbanStore`/`KanbanReadiness`/`KanbanAssignment`/`KanbanRetitle`
implementation is untouched. `SqliteKanbanStore` composes the functions
below as ordinary async instance methods that hand over its own
`self._conn`/`self._lock`, so there is still exactly one SQLite connection
and one lock per store instance.

CAS via a single `UPDATE ... WHERE` + `cursor.rowcount`: the WHERE clause
re-checks the free-or-stale condition against the CURRENT row (via the
SQLite JSON1 `json_extract` builtin over the `metadata` JSON already inside
`data`) at the moment of the write, inside a `BEGIN IMMEDIATE` transaction —
so there is no read-then-write race window at the SQL level. Every value
that reaches a query is a bound parameter — never string-concatenated.

`_serialize`/`_deserialize` are imported lazily, inside each function body
rather than at module level, from `sqlite.py` — `sqlite.py` imports THIS
module at its own top level to attach these functions as instance methods,
so a top-level import back would be circular. By the time any of these
functions actually runs, `swarmline.kanban.sqlite` has already finished
initializing, so the deferred import is safe (same lazy-import convention
this project already uses for optional dependencies).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import replace

from swarmline.kanban._time import canonical_iso, now_iso
from swarmline.kanban.types import KanbanNote, KanbanStatus, KanbanTask


def try_claim_sync(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    task_id: str,
    assignee: str,
    *,
    lease_id: str,
    stale_before: str,
) -> KanbanTask | None:
    from swarmline.kanban.sqlite import _deserialize, _serialize

    stale_before = canonical_iso(stale_before)
    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT data FROM kanban_tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Unknown task: {task_id!r}")
            task = _deserialize(row[0])
            now = now_iso()
            metadata = dict(task.metadata)
            metadata["lease_id"] = lease_id
            metadata["dispatched"] = True
            updated = replace(
                task,
                assignee=assignee,
                claimed_at=now,
                last_heartbeat_at=now,
                metadata=metadata,
            )
            update_cur = conn.execute(
                "UPDATE kanban_tasks SET data = ? WHERE id = ? AND ("
                "  json_extract(data, '$.metadata.lease_id') IS NULL"
                "  OR json_extract(data, '$.last_heartbeat_at') < ?"
                ")",
                (_serialize(updated), task_id, stale_before),
            )
            if update_cur.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise


def release_claim_sync(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    task_id: str,
    *,
    lease_id: str,
) -> KanbanTask:
    from swarmline.kanban.sqlite import _deserialize, _serialize

    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT data FROM kanban_tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Unknown task: {task_id!r}")
            task = _deserialize(row[0])
            if task.metadata.get("lease_id") != lease_id:
                conn.rollback()
                return task
            metadata = dict(task.metadata)
            metadata.pop("lease_id", None)
            updated = replace(task, metadata=metadata)
            conn.execute(
                "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                (_serialize(updated), task_id),
            )
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise


def list_claimable_sync(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    statuses: Sequence[KanbanStatus],
    stale_before: str,
    limit: int,
    include_fresh_claims: bool = False,
) -> list[KanbanTask]:
    from swarmline.kanban.sqlite import _deserialize

    stale_before = canonical_iso(stale_before)
    with lock:
        cur = conn.execute(
            """
            SELECT data FROM kanban_tasks
            WHERE id NOT IN (SELECT DISTINCT parent_id FROM kanban_task_links)
            ORDER BY rowid ASC
            """
        )
        rows = cur.fetchall()
    result: list[KanbanTask] = []
    for (raw,) in rows:
        task = _deserialize(raw)
        if task.status not in statuses:
            continue
        lease = task.metadata.get("lease_id")
        heartbeat = task.last_heartbeat_at
        is_stale = heartbeat is not None and heartbeat < stale_before
        if not include_fresh_claims and lease is not None and not is_stale:
            continue
        result.append(task)
        if len(result) >= limit:
            break
    return result


def append_note_sync(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    task_id: str,
    note: KanbanNote,
    *,
    max_notes: int,
) -> KanbanTask:
    from swarmline.kanban.sqlite import _deserialize, _serialize

    with lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT data FROM kanban_tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Unknown task: {task_id!r}")
            task = _deserialize(row[0])
            notes = list(task.metadata.get("notes", []))
            notes.append(
                {
                    "kind": note.kind,
                    "text": note.text,
                    "at": note.at,
                    "run_id": note.run_id,
                    "outcome": note.outcome,
                }
            )
            metadata = dict(task.metadata)
            metadata["notes"] = notes[-max_notes:]
            updated = replace(task, metadata=metadata)
            conn.execute(
                "UPDATE kanban_tasks SET data = ? WHERE id = ?",
                (_serialize(updated), task_id),
            )
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise
