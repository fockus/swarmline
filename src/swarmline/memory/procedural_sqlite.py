"""SQLite-backed procedural memory — FTS5 full-text search + success-rate ranking."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import replace

from swarmline.memory.procedural_types import Procedure, ProcedureStep

_DDL = """
CREATE TABLE IF NOT EXISTS procedures (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS procedures_fts USING fts5(
    proc_id, name, trigger_text, description, tags
);
"""


class SqliteProceduralMemory:
    """SQLite procedural memory with FTS5 full-text search."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.executescript(_DDL)
        self._conn.commit()

    @staticmethod
    def _ser(proc: Procedure) -> str:
        return json.dumps(
            {
                "id": proc.id,
                "name": proc.name,
                "description": proc.description,
                "trigger": proc.trigger,
                "steps": [
                    {
                        "tool_name": s.tool_name,
                        "args_template": s.args_template,
                        "expected_outcome": s.expected_outcome,
                    }
                    for s in proc.steps
                ],
                "success_count": proc.success_count,
                "failure_count": proc.failure_count,
                "tags": list(proc.tags),
                "metadata": proc.metadata,
            }
        )

    @staticmethod
    def _deser(raw: str) -> Procedure:
        d = json.loads(raw)
        steps = tuple(
            ProcedureStep(
                tool_name=s["tool_name"],
                args_template=s.get("args_template", {}),
                expected_outcome=s.get("expected_outcome", ""),
            )
            for s in d.get("steps", ())
        )
        return Procedure(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            trigger=d.get("trigger", ""),
            steps=steps,
            success_count=d.get("success_count", 0),
            failure_count=d.get("failure_count", 0),
            tags=tuple(d.get("tags", ())),
            metadata=d.get("metadata", {}),
        )

    def _store_sync(self, proc: Procedure) -> None:
        with self._lock:
            # Remove old FTS entry if exists
            self._conn.execute(
                "DELETE FROM procedures_fts WHERE proc_id = ?", (proc.id,)
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO procedures (id, data) VALUES (?, ?)",
                (proc.id, self._ser(proc)),
            )
            # Insert FTS entry
            tags_str = " ".join(proc.tags)
            self._conn.execute(
                "INSERT INTO procedures_fts (proc_id, name, trigger_text, description, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (proc.id, proc.name, proc.trigger, proc.description, tags_str),
            )
            self._conn.commit()

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Escape FTS5 special characters and wrap as phrase query."""
        # Remove FTS5 operators and special chars to prevent injection
        sanitized = query.replace('"', '""')
        return f'"{sanitized}"'

    def _suggest_sync(self, query: str, top_k: int) -> list[Procedure]:
        with self._lock:
            safe_query = self._sanitize_fts_query(query)
            cur = self._conn.execute(
                "SELECT p.data FROM procedures_fts f "
                "JOIN procedures p ON p.id = f.proc_id "
                "WHERE procedures_fts MATCH ? "
                "LIMIT ?",
                (safe_query, top_k * 3),
            )
            procs = [self._deser(r[0]) for r in cur.fetchall()]
        # Rank by success rate
        procs.sort(key=lambda p: p.success_rate, reverse=True)
        return procs[:top_k]

    def _record_outcome_sync(self, proc_id: str, success: bool) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM procedures WHERE id = ?", (proc_id,)
            )
            row = cur.fetchone()
            if not row:
                return
            proc = self._deser(row[0])
            if success:
                updated = replace(proc, success_count=proc.success_count + 1)
            else:
                updated = replace(proc, failure_count=proc.failure_count + 1)
            self._conn.execute(
                "UPDATE procedures SET data = ? WHERE id = ?",
                (self._ser(updated), proc_id),
            )
            self._conn.commit()

    def _get_sync(self, proc_id: str) -> Procedure | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM procedures WHERE id = ?", (proc_id,)
            )
            row = cur.fetchone()
            return self._deser(row[0]) if row else None

    def _count_sync(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT count(*) FROM procedures")
            return cur.fetchone()[0]

    # --- async API ---

    async def store(self, procedure: Procedure) -> None:
        await asyncio.to_thread(self._store_sync, procedure)

    async def suggest(self, query: str, *, top_k: int = 3) -> list[Procedure]:
        return await asyncio.to_thread(self._suggest_sync, query, top_k)

    async def record_outcome(self, proc_id: str, *, success: bool) -> None:
        await asyncio.to_thread(self._record_outcome_sync, proc_id, success)

    async def get(self, proc_id: str) -> Procedure | None:
        return await asyncio.to_thread(self._get_sync, proc_id)

    async def count(self) -> int:
        return await asyncio.to_thread(self._count_sync)
