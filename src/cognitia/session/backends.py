"""Session backends and memory scopes (Phase 8A).

Provides pluggable persistence for session state:
- InMemorySessionBackend - default, no external deps
- SqliteSessionBackend - zero-config file-based persistence
- MemoryScope - agent isolation via key namespacing
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import threading
from enum import Enum
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionBackend(Protocol):
    """Backend for session persistence."""

    async def save(self, key: str, state: dict[str, Any]) -> None: ...

    async def load(self, key: str) -> dict[str, Any] | None: ...

    async def delete(self, key: str) -> bool: ...

    async def list_keys(self) -> list[str]: ...


class MemoryScope(str, Enum):
    """Memory scope for agent isolation."""

    GLOBAL = "global"
    AGENT = "agent"
    SHARED = "shared"


def scoped_key(scope: MemoryScope, original_key: str) -> str:
    """Create a scope-prefixed key for namespace isolation."""
    return f"{scope.value}:{original_key}"


class InMemorySessionBackend:
    """Default in-memory session backend."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def save(self, key: str, state: dict[str, Any]) -> None:
        self._store[key] = copy.deepcopy(state)

    async def load(self, key: str) -> dict[str, Any] | None:
        state = self._store.get(key)
        return copy.deepcopy(state) if state is not None else None

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def list_keys(self) -> list[str]:
        return list(self._store.keys())


class SqliteSessionBackend:
    """SQLite-based session backend. Zero-config, file-based.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self, db_path: str = "cognitia_sessions.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions "
            "(key TEXT PRIMARY KEY, state TEXT NOT NULL)"
        )
        self._conn.commit()

    def _save_sync(self, key: str, state_json: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (key, state) VALUES (?, ?)",
                (key, state_json),
            )
            self._conn.commit()

    def _load_sync(self, key: str) -> str | None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT state FROM sessions WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def _delete_sync(self, key: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE key = ?", (key,)
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def _list_keys_sync(self) -> list[str]:
        with self._lock:
            cursor = self._conn.execute("SELECT key FROM sessions")
            return [row[0] for row in cursor.fetchall()]

    async def save(self, key: str, state: dict[str, Any]) -> None:
        state_json = json.dumps(state, ensure_ascii=False)
        await asyncio.to_thread(self._save_sync, key, state_json)

    async def load(self, key: str) -> dict[str, Any] | None:
        raw = await asyncio.to_thread(self._load_sync, key)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, key)

    async def list_keys(self) -> list[str]:
        return await asyncio.to_thread(self._list_keys_sync)

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()
