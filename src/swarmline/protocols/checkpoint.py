"""Checkpointer protocol — agent-STATE lineage per thread (domain layer).

Non-overlap boundary (REQ-017/REQ-018):

- This is NOT the ``EventJournal`` concern (``observability/`` event-stream
  audit/replay). The checkpointer persists agent *state* snapshots keyed by
  ``thread_id``; the journal persists an ordered *event* stream. No shared
  protocol, no shared storage.
- This is NOT ``resilience/checkpoint.py``'s ``CheckpointPort``. That port is
  a SYNC, single-key ``run_id -> state`` overwrite latch used for crash
  recovery of one run. It has no thread scoping, no lineage, and no history.
  The new ``Checkpointer`` protocol here MUST NOT route through it.

Three distinct protocols, zero shared symbols. ``Checkpointer`` supports
append-only history per thread with optional fork lineage (``parent_id``),
gating future time-travel/fork wrappers (Epic C1) as pure functions over
``put``/``get``/``list`` -- no protocol change needed for that later work.

Imports: stdlib + ``typing`` + ``collections.abc`` ONLY. Zero external deps.
``builtins`` is imported explicitly to spell the ``list`` method's return
type as ``builtins.list[CheckpointMeta]``: a Protocol method literally named
``list`` shadows the builtin ``list`` name when a static type checker
resolves the (stringified, PEP 563) return annotation in the class's own
namespace -- same type, spelled unambiguously.
"""

from __future__ import annotations

import builtins
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Checkpoint:
    """Immutable snapshot of agent state at one point in a thread's history."""

    id: str
    thread_id: str
    state: Mapping[str, Any]
    resource_id: str | None = None
    parent_id: str | None = None
    ts: float = field(default_factory=time.time)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckpointMeta:
    """Lightweight listing row for a thread's checkpoint history."""

    id: str
    thread_id: str
    parent_id: str | None
    ts: float
    resource_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Checkpointer(Protocol):
    """Thread-scoped, append-only checkpoint store — ISP: exactly 4 methods."""

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
        """Append a new checkpoint for ``thread_id``; return its id."""
        ...

    async def get(
        self, thread_id: str, *, checkpoint_id: str | None = None
    ) -> Checkpoint | None:
        """Return the checkpoint matching ``checkpoint_id``, or the latest
        checkpoint for ``thread_id`` when ``checkpoint_id`` is None. ``None``
        when the thread has no checkpoints."""
        ...

    async def list(self, thread_id: str) -> builtins.list[CheckpointMeta]:
        """Return the thread's history, oldest-to-newest."""
        ...

    async def delete(self, thread_id: str, *, checkpoint_id: str | None = None) -> int:
        """Delete one checkpoint (by id) or the whole thread; return count deleted."""
        ...
