"""Checkpointer implementations satisfying ``protocols.checkpoint.Checkpointer``.

``InMemoryCheckpointer`` (Task 2): zero-dep, append-only, in-process store.
``SqliteCheckpointer`` (Task 3): durable, WAL-mode, append-only store.
``SessionBackendCheckpointer`` lands in a later task of the
``checkpointer-protocol`` spec, in this same module (kept ≤400 lines total
across all implementations).
"""

from __future__ import annotations

import asyncio
import builtins
import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from swarmline.protocols.checkpoint import Checkpoint, CheckpointMeta


def _copy_checkpoint(cp: Checkpoint) -> Checkpoint:
    """Return a ``Checkpoint`` with ``state``/``metadata`` copied.

    Read-side defensive copy: mirrors the ``put``-side no-aliasing guarantee
    (REQ-008) so a caller mutating a returned ``Checkpoint`` can never
    corrupt stored history.
    """
    return Checkpoint(
        id=cp.id,
        thread_id=cp.thread_id,
        state=dict(cp.state),
        resource_id=cp.resource_id,
        parent_id=cp.parent_id,
        ts=cp.ts,
        metadata=dict(cp.metadata),
    )


class InMemoryCheckpointer:
    """Zero-dependency, append-only, in-process ``Checkpointer``.

    Each thread's history is a list of ``Checkpoint`` entries in insertion
    order (oldest first). ``put`` never overwrites: an explicit duplicate
    ``checkpoint_id`` appends a new history entry rather than replacing an
    existing one.
    """

    def __init__(self) -> None:
        self._threads: dict[str, list[Checkpoint]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        cid = checkpoint_id or uuid4().hex
        checkpoint = Checkpoint(
            id=cid,
            thread_id=thread_id,
            state=dict(state),
            resource_id=resource_id,
            parent_id=parent_id,
            metadata=dict(metadata or {}),
        )
        async with self._lock:
            self._threads.setdefault(thread_id, []).append(checkpoint)
        return cid

    async def get(
        self, thread_id: str, *, checkpoint_id: str | None = None
    ) -> Checkpoint | None:
        history = self._threads.get(thread_id)
        if not history:
            return None
        if checkpoint_id is None:
            return _copy_checkpoint(history[-1])
        for checkpoint in reversed(history):
            if checkpoint.id == checkpoint_id:
                return _copy_checkpoint(checkpoint)
        return None

    async def list(self, thread_id: str) -> builtins.list[CheckpointMeta]:
        history = self._threads.get(thread_id, [])
        return [
            CheckpointMeta(
                id=cp.id,
                thread_id=cp.thread_id,
                parent_id=cp.parent_id,
                ts=cp.ts,
                resource_id=cp.resource_id,
                metadata=dict(cp.metadata),
            )
            for cp in history
        ]

    async def delete(self, thread_id: str, *, checkpoint_id: str | None = None) -> int:
        async with self._lock:
            history = self._threads.get(thread_id)
            if not history:
                return 0
            if checkpoint_id is None:
                del self._threads[thread_id]
                return len(history)
            # Delete-all-matching: coherent with append-new duplicate ids
            # (get(checkpoint_id) returns the latest version of that id;
            # delete(checkpoint_id) removes every version of that id).
            kept = [cp for cp in history if cp.id != checkpoint_id]
            removed = len(history) - len(kept)
            self._threads[thread_id] = kept
            return removed

    async def close(self) -> None:
        """No-op — kept for API parity with durable backends (test/process
        teardown symmetry across the parametrized contract)."""
        return None


class SqliteCheckpointer:
    """SQLite-backed, append-only ``Checkpointer``. Mirrors
    ``SqliteTaskSessionStore`` (task_session_store.py): WAL + threading.Lock
    + asyncio.to_thread, so sqlite calls never block the event loop.

    Connection is LAZY (REQ-011): ``__init__`` touches neither the
    filesystem nor sqlite -- it only records ``db_path``. The connection,
    WAL pragma, and schema DDL are created on first use, inside
    ``_ensure_conn()``, which every ``_*_sync`` helper calls before its own
    query -- so even construction-time I/O runs off the event loop, under
    ``asyncio.to_thread``.

    Schema note: the caller-supplied ``id`` (checkpoint_id) is deliberately
    NON-unique -- the real primary key is a surrogate autoincrement ``pk``.
    This is required by the append-always contract: an explicit duplicate
    ``checkpoint_id`` must become a NEW row, never an overwrite, so every
    insert is a plain ``INSERT`` (never ``INSERT OR REPLACE``).

    Every read re-parses ``state``/``metadata`` from JSON into fresh dicts,
    so reads are isolated from stored rows for free -- no extra defensive
    copy is needed here (unlike ``InMemoryCheckpointer``, which shares
    Python objects and must copy explicitly).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _ensure_conn(self) -> sqlite3.Connection:
        """Connect + init schema on first use only (double-checked lock)."""
        if self._conn is not None:
            return self._conn
        with self._lock:
            if self._conn is not None:
                return self._conn
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS checkpoints ("
                "pk INTEGER PRIMARY KEY AUTOINCREMENT, "
                "id TEXT NOT NULL, "
                "thread_id TEXT NOT NULL, "
                "resource_id TEXT, "
                "parent_id TEXT, "
                "state TEXT NOT NULL, "
                "ts REAL NOT NULL, "
                "metadata TEXT NOT NULL DEFAULT '{}')"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cp_thread ON checkpoints(thread_id, ts)"
            )
            conn.commit()
            self._conn = conn
            return conn

    # --- sync helpers (run via asyncio.to_thread) ---

    def _put_sync(
        self,
        cid: str,
        thread_id: str,
        state_json: str,
        resource_id: str | None,
        parent_id: str | None,
        ts: float,
        metadata_json: str,
    ) -> None:
        conn = self._ensure_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO checkpoints "
                "(id, thread_id, resource_id, parent_id, state, ts, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, thread_id, resource_id, parent_id, state_json, ts, metadata_json),
            )
            conn.commit()

    def _get_sync(
        self, thread_id: str, checkpoint_id: str | None
    ) -> tuple[Any, ...] | None:
        conn = self._ensure_conn()
        with self._lock:
            if checkpoint_id is None:
                cursor = conn.execute(
                    "SELECT id, thread_id, resource_id, parent_id, state, ts, metadata "
                    "FROM checkpoints WHERE thread_id = ? "
                    "ORDER BY ts DESC, pk DESC LIMIT 1",
                    (thread_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT id, thread_id, resource_id, parent_id, state, ts, metadata "
                    "FROM checkpoints WHERE thread_id = ? AND id = ? "
                    "ORDER BY ts DESC, pk DESC LIMIT 1",
                    (thread_id, checkpoint_id),
                )
            return cursor.fetchone()

    def _list_sync(self, thread_id: str) -> builtins.list[tuple[Any, ...]]:
        conn = self._ensure_conn()
        with self._lock:
            cursor = conn.execute(
                "SELECT id, thread_id, resource_id, parent_id, ts, metadata "
                "FROM checkpoints WHERE thread_id = ? ORDER BY ts ASC, pk ASC",
                (thread_id,),
            )
            return cursor.fetchall()

    def _delete_sync(self, thread_id: str, checkpoint_id: str | None) -> int:
        conn = self._ensure_conn()
        with self._lock:
            if checkpoint_id is None:
                cursor = conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ? AND id = ?",
                    (thread_id, checkpoint_id),
                )
            conn.commit()
            return cursor.rowcount

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- async API ---

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        cid = checkpoint_id or uuid4().hex
        ts = time.time()
        state_json = json.dumps(dict(state), ensure_ascii=False)
        metadata_json = json.dumps(dict(metadata or {}), ensure_ascii=False)
        await asyncio.to_thread(
            self._put_sync,
            cid,
            thread_id,
            state_json,
            resource_id,
            parent_id,
            ts,
            metadata_json,
        )
        return cid

    async def get(
        self, thread_id: str, *, checkpoint_id: str | None = None
    ) -> Checkpoint | None:
        row = await asyncio.to_thread(self._get_sync, thread_id, checkpoint_id)
        if row is None:
            return None
        cid, tid, resource_id, parent_id, state_json, ts, metadata_json = row
        return Checkpoint(
            id=cid,
            thread_id=tid,
            state=json.loads(state_json),
            resource_id=resource_id,
            parent_id=parent_id,
            ts=ts,
            metadata=json.loads(metadata_json),
        )

    async def list(self, thread_id: str) -> builtins.list[CheckpointMeta]:
        rows = await asyncio.to_thread(self._list_sync, thread_id)
        return [
            CheckpointMeta(
                id=cid,
                thread_id=tid,
                parent_id=parent_id,
                ts=ts,
                resource_id=resource_id,
                metadata=json.loads(metadata_json),
            )
            for cid, tid, resource_id, parent_id, ts, metadata_json in rows
        ]

    async def delete(self, thread_id: str, *, checkpoint_id: str | None = None) -> int:
        return await asyncio.to_thread(self._delete_sync, thread_id, checkpoint_id)

    async def close(self) -> None:
        """Close the SQLite connection (test/process teardown). Idempotent:
        safe to call more than once, or before any operation has connected."""
        await asyncio.to_thread(self._close_sync)
