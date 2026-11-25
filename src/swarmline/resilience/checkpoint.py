"""OSS-T4 — Durable execution: checkpoint + recovery + stream-chunk.

REQ-OSS-020: persist checkpoint per tool-call, resume on restart.
REQ-OSS-021: recovery strategy dispatch — RETRY/SKIP/ROLLBACK/MANUAL.
REQ-OSS-051: stdlib-only; zero coupling to taskloom/FastAPI/SQLAlchemy/Lobu.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol


# ---------------------------------------------------------------------------
# Reserved metadata keys
# ---------------------------------------------------------------------------

#: Reserved key injected by CheckpointWriter.  Callers must NOT use this key.
CHECKPOINT_KEY_STEP: str = "_step"

#: Reserved key injected by CheckpointWriter.  Callers must NOT use this key.
CHECKPOINT_KEY_TOTAL: str = "_total_steps"


def _redact_leaves(value: object) -> object:
    """Apply ``redact_secrets`` to every string leaf of a JSON-shaped value.

    Walks the whole payload rather than a list of known keys: checkpoint state
    accumulates new keys as context-engineering grows (offload projections,
    write-failure fallbacks, compression history, tool-schema snapshots), and a
    key list would silently stop covering them. Non-string leaves are returned
    as-is, so numbers/None/bools keep their exact JSON type.
    """
    from swarmline.observability.redaction import redact_secrets

    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_leaves(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_leaves(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Domain value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    """Immutable snapshot of run state at a completed step."""

    run_id: str
    step_index: int
    total_steps: int
    state: dict[str, object]
    created_at: datetime


# ---------------------------------------------------------------------------
# Port (Protocol — ISP ≤5 methods)
# ---------------------------------------------------------------------------


class CheckpointPort(Protocol):
    """Generic persistent checkpoint store — ISP ≤ 4 methods.

    Implementations must be sync.  ``CheckpointWriter`` wraps them in
    async methods for use inside the async react loop.
    """

    def save_checkpoint(self, run_id: str, state: dict[str, object]) -> None:
        """Persist ``state`` under ``run_id``; overwrite any prior value."""
        ...

    def load_checkpoint(self, run_id: str) -> dict[str, object] | None:
        """Return the saved state for ``run_id``, or ``None`` if absent."""
        ...

    def clear_checkpoint(self, run_id: str) -> None:
        """Delete the checkpoint for ``run_id`` (noop if absent)."""
        ...

    def list_orphaned(self) -> list[str]:
        """Return all ``run_id`` keys currently held (for crash-recovery sweeps)."""
        ...


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------


class InMemoryCheckpointStore:
    """Synchronous dict-backed reference implementation of ``CheckpointPort``.

    Thread-safety: not guaranteed; use an external lock if needed.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, object]] = {}

    def save_checkpoint(self, run_id: str, state: dict[str, object]) -> None:
        """Overwrite any prior checkpoint for ``run_id``."""
        self._store[run_id] = state

    def load_checkpoint(self, run_id: str) -> dict[str, object] | None:
        """Return the saved state or ``None``."""
        return self._store.get(run_id)

    def clear_checkpoint(self, run_id: str) -> None:
        """Remove ``run_id`` from the store; silently ignore unknown keys."""
        self._store.pop(run_id, None)

    def list_orphaned(self) -> list[str]:
        """Return all currently saved run_ids."""
        return list(self._store.keys())


# ---------------------------------------------------------------------------
# CheckpointWriter — thin async facade used by the react loop
# ---------------------------------------------------------------------------


class CheckpointWriter:
    """Async facade that writes namespaced checkpoints after each tool-call.

    Args:
        store:     Any object satisfying ``CheckpointPort``.
        namespace: String prefix applied to every ``run_id`` before storage,
                   e.g. ``"swarmline:"`` (default).  Pass ``""`` for no prefix.

    Reserved keys ``CHECKPOINT_KEY_STEP`` and ``CHECKPOINT_KEY_TOTAL`` are
    injected into every saved state dict.  Callers must not use those keys.
    """

    def __init__(self, store: CheckpointPort, *, namespace: str = "swarmline:") -> None:
        self._store = store
        self._namespace = namespace

    def _key(self, run_id: str) -> str:
        return f"{self._namespace}{run_id}"

    async def after_tool_call(
        self,
        *,
        run_id: str,
        step: int,
        total_steps: int,
        state: dict[str, object],
    ) -> None:
        """Persist a checkpoint immediately after a successful tool-call.

        Injects ``CHECKPOINT_KEY_STEP`` and ``CHECKPOINT_KEY_TOTAL`` into a
        copy of ``state`` before saving; the caller's dict is not mutated.

        Secrets are stripped from the persisted COPY only (BL-82). Tool output
        reaches durable storage through several state keys — offload
        projections, write-failure fallbacks that hold the whole body,
        compression summaries, and small results still inline in the message
        history — so an API key a tool happened to echo would otherwise outlive
        the run inside the host's database. The live in-memory ``state`` keeps
        the real bytes: the running agent must still see what its tool returned.
        """
        payload: dict[str, object] = {
            **{key: _redact_leaves(value) for key, value in state.items()},
            CHECKPOINT_KEY_STEP: step,
            CHECKPOINT_KEY_TOTAL: total_steps,
        }
        self._store.save_checkpoint(self._key(run_id), payload)

    async def on_run_complete(self, *, run_id: str) -> None:
        """Clear the checkpoint after the run completes successfully."""
        self._store.clear_checkpoint(self._key(run_id))

    async def load(self, run_id: str) -> dict[str, object] | None:
        """Return the previously saved state for ``run_id``, or ``None``."""
        return self._store.load_checkpoint(self._key(run_id))


# ---------------------------------------------------------------------------
# RecoveryStrategy enum
# ---------------------------------------------------------------------------


class RecoveryStrategy(enum.Enum):
    """Strategy to apply when recovering from a crashed run."""

    RETRY = "retry"
    SKIP = "skip"
    ROLLBACK = "rollback"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# CrashRecoveryService
# ---------------------------------------------------------------------------


class CrashRecoveryService:
    """Manages Checkpoint lifecycle and dispatches recovery actions.

    Stores checkpoints in an internal dict (reference impl; swap for a
    persistent adapter in production via dependency injection).

    Args:
        clock: Optional callable returning the current ``datetime``.
               Defaults to ``datetime.now(UTC)`` when ``None``.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock
        self._store: dict[str, list[Checkpoint]] = {}

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else datetime.now(UTC)

    def create_checkpoint(
        self,
        run_id: str,
        step_index: int,
        state: dict[str, object],
    ) -> Checkpoint:
        """Create and store a new checkpoint; return the immutable VO."""
        cp = Checkpoint(
            run_id=run_id,
            step_index=step_index,
            total_steps=0,
            state=state,
            created_at=self._now(),
        )
        self._store.setdefault(run_id, []).append(cp)
        return cp

    def get_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Return the checkpoint with the highest step_index, or ``None``."""
        checkpoints = self._store.get(run_id, [])
        if not checkpoints:
            return None
        return max(checkpoints, key=lambda cp: cp.step_index)

    def recover(self, run_id: str, strategy: RecoveryStrategy) -> str:
        """Dispatch a recovery action and return a human-readable description.

        Each strategy branch is intentionally distinct so callers can assert
        on the returned string in tests.
        """
        latest = self.get_latest_checkpoint(run_id)
        step_info = f"step={latest.step_index}" if latest else "no checkpoint"

        match strategy:
            case RecoveryStrategy.RETRY:
                return f"retry from {step_info} for run={run_id}"
            case RecoveryStrategy.SKIP:
                return f"skip {step_info} for run={run_id}"
            case RecoveryStrategy.ROLLBACK:
                return f"rollback to {step_info} for run={run_id}"
            case RecoveryStrategy.MANUAL:
                return f"manual intervention required for run={run_id} at {step_info}"

    def cleanup_checkpoints(self, run_id: str) -> int:
        """Remove all checkpoints for ``run_id``; return the count removed."""
        return len(self._store.pop(run_id, []))


# ---------------------------------------------------------------------------
# RunStreamChunk discriminated union
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunStreamChunk:
    """Discriminated union over streaming run output.

    ``kind="tool"``  → tool call completed (``tool_name`` / ``tool_result``).
    ``kind="final"`` → final agent response (``final_text``).
    Use ``is_tool`` / ``is_final`` as convenience predicates.
    """

    kind: Literal["tool", "final"]
    tool_name: str | None = None
    tool_result: str | None = None
    final_text: str | None = None

    @property
    def is_tool(self) -> bool:
        """True when this chunk represents a completed tool call."""
        return self.kind == "tool"

    @property
    def is_final(self) -> bool:
        """True when this chunk represents the final agent response."""
        return self.kind == "final"


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "CHECKPOINT_KEY_STEP",
    "CHECKPOINT_KEY_TOTAL",
    "Checkpoint",
    "CheckpointPort",
    "CheckpointWriter",
    "CrashRecoveryService",
    "InMemoryCheckpointStore",
    "RecoveryStrategy",
    "RunStreamChunk",
]
