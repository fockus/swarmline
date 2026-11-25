"""InMemoryAuditTrail — append-only, thread-safe audit storage.

Implements AuditTrailPort. Stores entries per run_id with Lock-based
thread safety. Entries are never removed — only appended.
"""

from __future__ import annotations

import threading

from swarmline.governance.types import AuditEntry, AuditTrail


class InMemoryAuditTrail:
    """Append-only in-memory audit trail with thread-safe writes.

    Satisfies AuditTrailPort protocol.
    """

    def __init__(self) -> None:
        self._entries: dict[str, list[AuditEntry]] = {}
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        """Append an audit entry. Thread-safe."""
        with self._lock:
            self._entries.setdefault(entry.run_id, []).append(entry)

    def get_trail(self, run_id: str) -> AuditTrail:
        """Return full AuditTrail for a run. Empty tuple if unknown run."""
        with self._lock:
            entries = list(self._entries.get(run_id, []))
        return AuditTrail(run_id=run_id, entries=tuple(entries))

    def get_entries_by_actor(self, run_id: str, actor: str) -> list[AuditEntry]:
        """Return entries filtered by actor for a given run."""
        with self._lock:
            entries = list(self._entries.get(run_id, []))
        return [e for e in entries if e.actor == actor]
