"""ActivityLog — persistent structured audit trail.

Provides:
- ActivityLog: Protocol defining the audit trail contract (ISP: 3 methods).
- InMemoryActivityLog: Default in-memory implementation.
- SqliteActivityLog: SQLite-based persistent implementation.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cognitia.observability.activity_types import ActivityEntry, ActivityFilter


@runtime_checkable
class ActivityLog(Protocol):
    """Persistent structured audit trail. ISP: 3 methods."""

    async def log(self, entry: ActivityEntry) -> None: ...

    async def query(self, filter: ActivityFilter) -> list[ActivityEntry]: ...

    async def count(self, filter: ActivityFilter) -> int: ...


# ---------------------------------------------------------------------------
# InMemory implementation
# ---------------------------------------------------------------------------


class InMemoryActivityLog:
    """Default in-memory activity log. Thread-safe via asyncio.Lock.

    Args:
        max_entries: Maximum number of entries to retain. Oldest entries
            are evicted when this limit is exceeded. 0 means unlimited.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[ActivityEntry] = []
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    async def log(self, entry: ActivityEntry) -> None:
        async with self._lock:
            self._entries.append(entry)
            if self._max_entries > 0 and len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]

    async def query(self, filter: ActivityFilter) -> list[ActivityEntry]:
        async with self._lock:
            results = [e for e in self._entries if _matches(e, filter)]
        return sorted(results, key=lambda e: e.timestamp, reverse=True)

    async def count(self, filter: ActivityFilter) -> int:
        return len(await self.query(filter))


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------


class SqliteActivityLog:
    """SQLite-based activity log. Zero-config, file-based persistence.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    PRAGMA journal_mode=WAL for concurrent read safety.
    """

    def __init__(self, db_path: str = "cognitia_activity.db", *, max_entries: int = 10_000) -> None:
        self._db_path = db_path
        self._max_entries = max_entries
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS activity_log ("
                "id TEXT PRIMARY KEY, "
                "actor_type TEXT NOT NULL, "
                "actor_id TEXT NOT NULL, "
                "action TEXT NOT NULL, "
                "entity_type TEXT NOT NULL, "
                "entity_id TEXT NOT NULL, "
                "details TEXT NOT NULL, "
                "timestamp REAL NOT NULL"
                ")"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_al_actor "
                "ON activity_log(actor_type, actor_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_al_entity "
                "ON activity_log(entity_type, entity_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_al_timestamp "
                "ON activity_log(timestamp)"
            )
            self._conn.commit()

    # -- sync helpers -------------------------------------------------------

    def _log_sync(self, entry: ActivityEntry) -> None:
        from cognitia.observability.activity_types import ActorType  # noqa: F811

        with self._lock:
            self._conn.execute(
                "INSERT INTO activity_log "
                "(id, actor_type, actor_id, action, entity_type, entity_id, details, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.actor_type.value if isinstance(entry.actor_type, ActorType) else entry.actor_type,
                    entry.actor_id,
                    entry.action,
                    entry.entity_type,
                    entry.entity_id,
                    json.dumps(entry.details, ensure_ascii=False),
                    entry.timestamp,
                ),
            )
            # Evict oldest entries if over max_entries
            if self._max_entries > 0:
                row = self._conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()
                total = row[0] if row else 0
                if total > self._max_entries:
                    overflow = total - self._max_entries
                    oldest_ids = [
                        r[0]
                        for r in self._conn.execute(
                            "SELECT id FROM activity_log ORDER BY timestamp ASC LIMIT ?",
                            (overflow,),
                        ).fetchall()
                    ]
                    if oldest_ids:
                        placeholders = ",".join("?" for _ in oldest_ids)
                        self._conn.execute(
                            f"DELETE FROM activity_log WHERE id IN ({placeholders})",
                            oldest_ids,
                        )
            self._conn.commit()

    def _query_sync(self, filter: ActivityFilter) -> list[ActivityEntry]:
        from cognitia.observability.activity_types import ActivityEntry as AE
        from cognitia.observability.activity_types import ActorType

        clauses: list[str] = []
        params: list[object] = []

        if filter.actor_type is not None:
            clauses.append("actor_type = ?")
            params.append(filter.actor_type.value if isinstance(filter.actor_type, ActorType) else filter.actor_type)
        if filter.actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(filter.actor_id)
        if filter.action is not None:
            clauses.append("action = ?")
            params.append(filter.action)
        if filter.entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(filter.entity_type)
        if filter.entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(filter.entity_id)
        if filter.since is not None:
            clauses.append("timestamp >= ?")
            params.append(filter.since)
        if filter.until is not None:
            clauses.append("timestamp <= ?")
            params.append(filter.until)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT id, actor_type, actor_id, action, entity_type, entity_id, details, timestamp FROM activity_log WHERE {where} ORDER BY timestamp DESC"

        with self._lock:
            cursor = self._conn.execute(sql, params)
            rows = cursor.fetchall()

        return [
            AE(
                id=row[0],
                actor_type=ActorType(row[1]),
                actor_id=row[2],
                action=row[3],
                entity_type=row[4],
                entity_id=row[5],
                details=json.loads(row[6]),
                timestamp=row[7],
            )
            for row in rows
        ]

    def _count_sync(self, filter: ActivityFilter) -> int:
        from cognitia.observability.activity_types import ActorType

        clauses: list[str] = []
        params: list[object] = []

        if filter.actor_type is not None:
            clauses.append("actor_type = ?")
            params.append(filter.actor_type.value if isinstance(filter.actor_type, ActorType) else filter.actor_type)
        if filter.actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(filter.actor_id)
        if filter.action is not None:
            clauses.append("action = ?")
            params.append(filter.action)
        if filter.entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(filter.entity_type)
        if filter.entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(filter.entity_id)
        if filter.since is not None:
            clauses.append("timestamp >= ?")
            params.append(filter.since)
        if filter.until is not None:
            clauses.append("timestamp <= ?")
            params.append(filter.until)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT COUNT(*) FROM activity_log WHERE {where}"

        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    # -- async API ----------------------------------------------------------

    async def log(self, entry: ActivityEntry) -> None:
        await asyncio.to_thread(self._log_sync, entry)

    async def query(self, filter: ActivityFilter) -> list[ActivityEntry]:
        return await asyncio.to_thread(self._query_sync, filter)

    async def count(self, filter: ActivityFilter) -> int:
        return await asyncio.to_thread(self._count_sync, filter)

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Filter matching helper (for InMemory)
# ---------------------------------------------------------------------------


def _matches(entry: ActivityEntry, filter: ActivityFilter) -> bool:
    """Check if entry matches all non-None filter fields."""
    if filter.actor_type is not None and entry.actor_type != filter.actor_type:
        return False
    if filter.actor_id is not None and entry.actor_id != filter.actor_id:
        return False
    if filter.action is not None and entry.action != filter.action:
        return False
    if filter.entity_type is not None and entry.entity_type != filter.entity_type:
        return False
    if filter.entity_id is not None and entry.entity_id != filter.entity_id:
        return False
    if filter.since is not None and entry.timestamp < filter.since:
        return False
    if filter.until is not None and entry.timestamp > filter.until:
        return False
    return True
