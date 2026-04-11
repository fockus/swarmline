"""SQLite-backed episodic memory with FTS5 full-text search."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime

from swarmline.memory.episodic_types import Episode


class SqliteEpisodicMemory:
    """Episodic memory with SQLite storage and FTS5 search."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_tables()
        return self._conn

    def _init_tables(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                key_decisions TEXT NOT NULL DEFAULT '[]',
                tools_used TEXT NOT NULL DEFAULT '[]',
                outcome TEXT NOT NULL DEFAULT 'unknown',
                session_id TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                id, summary, key_decisions, tags,
                content=episodes,
                content_rowid=rowid
            );
            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, id, summary, key_decisions, tags)
                VALUES (new.rowid, new.id, new.summary, new.key_decisions, new.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS episodes_bd BEFORE DELETE ON episodes BEGIN
                INSERT INTO episodes_fts(episodes_fts, rowid, id, summary, key_decisions, tags)
                VALUES('delete', old.rowid, old.id, old.summary, old.key_decisions, old.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS episodes_bu BEFORE UPDATE ON episodes BEGIN
                INSERT INTO episodes_fts(episodes_fts, rowid, id, summary, key_decisions, tags)
                VALUES('delete', old.rowid, old.id, old.summary, old.key_decisions, old.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, id, summary, key_decisions, tags)
                VALUES (new.rowid, new.id, new.summary, new.key_decisions, new.tags);
            END;
        """)

    def _row_to_episode(self, row: tuple) -> Episode:
        return Episode(
            id=row[0],
            summary=row[1],
            key_decisions=tuple(json.loads(row[2])),
            tools_used=tuple(json.loads(row[3])),
            outcome=row[4],
            session_id=row[5],
            timestamp=datetime.fromisoformat(row[6]),
            tags=tuple(json.loads(row[7])),
            metadata=json.loads(row[8]),
        )

    async def store(self, episode: Episode) -> None:
        def _insert() -> None:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """INSERT OR REPLACE INTO episodes
                       (id, summary, key_decisions, tools_used, outcome,
                        session_id, timestamp, tags, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        episode.id,
                        episode.summary,
                        json.dumps(list(episode.key_decisions)),
                        json.dumps(list(episode.tools_used)),
                        episode.outcome,
                        episode.session_id,
                        episode.timestamp.isoformat(),
                        json.dumps(list(episode.tags)),
                        json.dumps(episode.metadata),
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    async def recall(self, query: str, *, top_k: int = 5) -> list[Episode]:
        def _search() -> list[Episode]:
            with self._lock:
                conn = self._get_conn()
                # FTS5 query — sanitize to prevent operator injection
                sanitized = query.replace('"', '""')
                safe_query = f'"{sanitized}"'
                try:
                    rows = conn.execute(
                        """SELECT e.* FROM episodes e
                           JOIN episodes_fts f ON e.rowid = f.rowid
                           WHERE episodes_fts MATCH ?
                           ORDER BY rank
                           LIMIT ?""",
                        (safe_query, top_k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    # Fallback to LIKE if FTS fails — escape LIKE wildcards
                    escaped = (
                        query.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                    rows = conn.execute(
                        """SELECT * FROM episodes
                           WHERE summary LIKE ? ESCAPE '\\'
                           LIMIT ?""",
                        (f"%{escaped}%", top_k),
                    ).fetchall()
                return [self._row_to_episode(r) for r in rows]

        return await asyncio.to_thread(_search)

    async def recall_recent(self, n: int = 10) -> list[Episode]:
        def _recent() -> list[Episode]:
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT ?",
                    (n,),
                ).fetchall()
                return [self._row_to_episode(r) for r in rows]

        return await asyncio.to_thread(_recent)

    async def recall_by_tag(self, tag: str) -> list[Episode]:
        def _by_tag() -> list[Episode]:
            with self._lock:
                conn = self._get_conn()
                # JSON array contains check
                rows = conn.execute(
                    """SELECT * FROM episodes
                       WHERE tags LIKE ?
                       ORDER BY timestamp DESC""",
                    (f'%"{tag}"%',),
                ).fetchall()
                return [self._row_to_episode(r) for r in rows]

        return await asyncio.to_thread(_by_tag)

    async def count(self) -> int:
        def _count() -> int:
            with self._lock:
                conn = self._get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) FROM episodes",
                ).fetchone()
                return row[0] if row else 0

        return await asyncio.to_thread(_count)
