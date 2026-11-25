"""Memory versioning — namespace commit/history/diff/restore.

MemoryCommitPort: ISP-compliant protocol (4 methods).
InMemoryCommitStore: reference implementation, zero external dependencies.

Generic str ids throughout; no product (tenant/workspace/FastAPI/SQLAlchemy) coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class MemorySnapshot:
    """Immutable point-in-time snapshot of a memory namespace.

    Args:
        namespace: Generic string key identifying the memory namespace (e.g. 'agent:123').
        version:   Monotonically increasing integer per namespace.
        entries:   The full set of text entries captured at this version.
        created_at: UTC timestamp of the commit; defaults to now if omitted.
        metadata:  Arbitrary key/value context (e.g. ``{"restored_from": 2}``).
    """

    namespace: str
    version: int
    entries: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemoryCommitPort(Protocol):
    """Port for versioned memory snapshots (ISP — 4 methods).

    All ids are plain ``str``. Implementations are free to persist snapshots
    in any storage backend.
    """

    async def commit(self, namespace: str, entries: list[str]) -> MemorySnapshot:
        """Record *entries* as a new snapshot version of *namespace*.

        Returns the newly created :class:`MemorySnapshot`.
        """
        ...

    async def history(
        self,
        namespace: str,
        limit: int = 10,
    ) -> list[MemorySnapshot]:
        """Return up to *limit* snapshots for *namespace*, newest first."""
        ...

    async def diff(self, namespace: str, v1: int, v2: int) -> list[str]:
        """Return entries present in snapshot *v2* but absent from snapshot *v1*."""
        ...

    async def restore(self, namespace: str, version: int) -> MemorySnapshot:
        """Restore *namespace* to the entries recorded in *version*.

        Appends a new snapshot (so history is never truncated) and returns it.
        Raises :exc:`ValueError` when *version* does not exist.
        """
        ...


class InMemoryCommitStore:
    """Reference in-process implementation of :class:`MemoryCommitPort`.

    All state lives in a plain dict keyed by namespace. Thread-safety is not
    a goal here — use a persistent backend (SQLite / Postgres) in production.
    """

    def __init__(self) -> None:
        # namespace -> list[MemorySnapshot] in insertion order (oldest first)
        self._store: dict[str, list[MemorySnapshot]] = {}

    async def commit(self, namespace: str, entries: list[str]) -> MemorySnapshot:
        """Record *entries* as a new snapshot for *namespace*."""
        snaps = self._store.setdefault(namespace, [])
        version = (snaps[-1].version + 1) if snaps else 1
        snap = MemorySnapshot(
            namespace=namespace,
            version=version,
            entries=tuple(entries),
        )
        snaps.append(snap)
        return snap

    async def history(
        self,
        namespace: str,
        limit: int = 10,
    ) -> list[MemorySnapshot]:
        """Return up to *limit* snapshots newest-first."""
        snaps = self._store.get(namespace, [])
        return list(reversed(snaps))[:limit]

    async def diff(self, namespace: str, v1: int, v2: int) -> list[str]:
        """Return entries in snapshot *v2* that are absent from snapshot *v1*."""
        snap1 = self._get_version(namespace, v1)
        snap2 = self._get_version(namespace, v2)
        set1 = set(snap1.entries)
        return [e for e in snap2.entries if e not in set1]

    async def restore(self, namespace: str, version: int) -> MemorySnapshot:
        """Append a new snapshot whose entries equal those of *version*."""
        source = self._get_version(namespace, version)
        snaps = self._store.setdefault(namespace, [])
        new_version = (snaps[-1].version + 1) if snaps else 1
        restored = MemorySnapshot(
            namespace=namespace,
            version=new_version,
            entries=source.entries,
            metadata={"restored_from": version},
        )
        snaps.append(restored)
        return restored

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_version(self, namespace: str, version: int) -> MemorySnapshot:
        snaps = self._store.get(namespace, [])
        for snap in snaps:
            if snap.version == version:
                return snap
        raise ValueError(
            f"Snapshot version={version} not found in namespace={namespace!r}"
        )
