"""Event journal port -- durable, replayable append-only event log.

Dependency-light by design (stdlib only), mirroring the EventBus split in
this package (``event_bus.py`` = Protocol + in-process impl, heavy
implementations live in sibling modules such as ``event_bus_redis.py`` /
``event_bus_nats.py``). Provides:

- JournalEntry: frozen record (seq, schema_version, timestamp, event_type, data).
- EventJournal: Protocol -- append events, get the highest assigned seq.
- ReplayReader: Protocol -- replay entries by inclusive seq range.
- InMemoryEventJournal: in-process journal backed by a list (tests, ephemeral runs).

For a durable, file-backed implementation see ``jsonl_journal.JsonlEventJournal``.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class JournalEntry:
    """One immutable, replayable journal record."""

    seq: int
    schema_version: int
    timestamp: str
    event_type: str
    data: dict[str, object]


@runtime_checkable
class EventJournal(Protocol):
    """Port: append-only event journal with monotonic sequence numbers."""

    async def append(self, event_type: str, data: dict[str, object]) -> int:
        """Append one event; returns the assigned sequence number (>= 1)."""
        ...

    async def last_seq(self) -> int:
        """Return the highest assigned sequence number (0 if empty)."""
        ...


@runtime_checkable
class ReplayReader(Protocol):
    """Port: replay journal entries over an inclusive sequence range."""

    def read(
        self, *, since: int = 0, until: int | None = None
    ) -> AsyncIterator[JournalEntry]:
        """Yield entries with ``since <= seq <= until`` in seq order.

        ``until=None`` means open-ended (no upper bound). Each yielded
        ``JournalEntry`` is isolated from internal storage -- mutating
        ``entry.data`` must never affect a subsequent ``read()`` call.
        """
        ...


class InMemoryEventJournal:
    """In-process event journal backed by a list, guarded by an asyncio.Lock.

    Implements both ``EventJournal`` and ``ReplayReader``. Suitable for tests
    and ephemeral single-process runs; not durable across restarts (see
    ``jsonl_journal.JsonlEventJournal`` for a durable, file-backed alternative).
    """

    def __init__(self, *, schema_version: int = 1) -> None:
        self._schema_version = schema_version
        self._entries: list[JournalEntry] = []
        self._lock = asyncio.Lock()

    async def append(self, event_type: str, data: dict[str, object]) -> int:
        """Append one event; assigns the next sequential seq under lock."""
        async with self._lock:
            seq = len(self._entries) + 1
            entry = JournalEntry(
                seq=seq,
                schema_version=self._schema_version,
                timestamp=datetime.now(tz=UTC).isoformat(),
                event_type=event_type,
                data=copy.deepcopy(data),
            )
            self._entries.append(entry)
            return seq

    async def last_seq(self) -> int:
        """Return the highest assigned seq (0 if the journal is empty)."""
        async with self._lock:
            return len(self._entries)

    async def read(
        self, *, since: int = 0, until: int | None = None
    ) -> AsyncIterator[JournalEntry]:
        """Yield a deep-copied snapshot of entries in ``[since, until]``."""
        async with self._lock:
            snapshot = list(self._entries)
        for entry in snapshot:
            if entry.seq < since:
                continue
            if until is not None and entry.seq > until:
                continue
            yield JournalEntry(
                seq=entry.seq,
                schema_version=entry.schema_version,
                timestamp=entry.timestamp,
                event_type=entry.event_type,
                data=copy.deepcopy(entry.data),
            )
