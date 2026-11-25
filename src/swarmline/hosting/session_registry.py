"""RuntimeSessionRegistry — generic hosted session lifecycle for swarmline.

Ported from taskloom HostedRuntimeManager (src/taskloom/application/services/
hosted_runtime_manager.py) and generalised:
  - NO tenant/workspace/AccessContext/billing/FastAPI/SQLAlchemy/Lobu.
  - Session keys are plain str (session_id, owner_id).
  - Finalize is a callback (FinalizeCallback), not a product service.
  - Clock is injected (ClockFactory) — no datetime.now() in logic paths.

REQ-OSS-050: opt-in / additive — does not modify any existing swarmline module.
REQ-OSS-051: zero product coupling — grep this file for the above list to verify.

Lifecycle:
  register(session_id, owner_id) — track the owner; no heartbeat yet.
  admit(session_id)              — mark in-flight, emit one immediate heartbeat.
  complete(session_id)           — remove from in-flight (run finished cleanly).
  drain(timeout, on_finalize)    — finalize all in-flight sessions within the
                                   timeout budget, then clear the in-flight set.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from swarmline.hosting.ports import ClockFactory, FinalizeCallback, HeartbeatEmitter

logger = logging.getLogger(__name__)


@dataclass
class _SessionEntry:
    """Book-keeping for one registered session."""

    session_id: str
    owner_id: str
    admitted: bool = field(default=False)


class RuntimeSessionRegistry:
    """Manages in-flight hosted sessions and orchestrates graceful drain.

    Responsibilities:
      - Track registered sessions (session_id → owner_id).
      - Admit sessions to in-flight state with an immediate heartbeat.
      - Remove sessions when they complete.
      - Drain: invoke on_finalize for every in-flight session within a timeout,
        then clear the in-flight set.

    Args:
        now_factory:        Injected clock — returns current datetime.
                            Pass ``lambda: datetime(2024, 1, 1, tzinfo=UTC)``
                            in tests for deterministic assertions.
        heartbeat_emitter:  HeartbeatEmitter called at admission time.
                            beat_now failures are propagated so the caller can
                            clean up (no orphaned ACTIVE row without a heartbeat).
    """

    def __init__(
        self,
        *,
        now_factory: ClockFactory,
        heartbeat_emitter: HeartbeatEmitter,
    ) -> None:
        self._now_factory = now_factory
        self._hb_emitter = heartbeat_emitter
        self._sessions: dict[str, _SessionEntry] = {}
        self._draining: bool = False

    # ------------------------------------------------------------------
    # Public read properties
    # ------------------------------------------------------------------

    @property
    def inflight(self) -> frozenset[str]:
        """Return the current set of admitted (in-flight) session_ids."""
        return frozenset(e.session_id for e in self._sessions.values() if e.admitted)

    def owner_of(self, session_id: str) -> str | None:
        """Return the owner_id for *session_id*, or None if not registered."""
        entry = self._sessions.get(session_id)
        return entry.owner_id if entry is not None else None

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def register(self, session_id: str, owner_id: str) -> None:
        """Register a session under *owner_id*.

        Safe to call during drain — only admit() is blocked after drain starts.

        Args:
            session_id: Generic string identifier.
            owner_id:   Generic string identifier for the session owner
                        (e.g. a user or agent id — NOT a tenant/workspace id).
        """
        self._sessions[session_id] = _SessionEntry(
            session_id=session_id,
            owner_id=owner_id,
        )
        logger.debug(
            "SessionRegistry: registered session=%s owner=%s", session_id, owner_id
        )

    async def admit(self, session_id: str) -> None:
        """Admit a registered session: mark in-flight and emit a heartbeat.

        Called when the session begins active processing.  Emits one immediate
        heartbeat so a crash detector can distinguish admitted sessions from
        registered-but-never-started ones.

        Args:
            session_id: Must have been previously registered.

        Raises:
            RuntimeError: Registry is draining — new admits are rejected.
            Exception:    Propagated from HeartbeatEmitter.beat_now on write failure.
        """
        if self._draining:
            raise RuntimeError(
                f"RuntimeSessionRegistry is draining — cannot admit '{session_id}'"
            )
        entry = self._sessions.get(session_id)
        if entry is None:
            logger.warning(
                "admit: session_id=%s is not registered — auto-registering", session_id
            )
            entry = _SessionEntry(session_id=session_id, owner_id="unknown")
            self._sessions[session_id] = entry

        ts = self._now_factory()
        await self._hb_emitter.beat_now(session_id, ts)
        # Re-check after the await: drain() may have run concurrently and set
        # _draining=True while beat_now was suspended.  Without this guard,
        # entry.admitted would be set True after drain already read an empty
        # inflight set, leaking a session that was never finalized.
        if self._draining:
            raise RuntimeError(
                f"RuntimeSessionRegistry is draining — cannot admit '{session_id}'"
            )
        entry.admitted = True
        logger.debug("SessionRegistry: admitted session=%s at ts=%s", session_id, ts)

    def complete(self, session_id: str) -> None:
        """Mark *session_id* as completed — remove from in-flight.

        No-op when the session is not registered (idempotent).

        Args:
            session_id: The session that finished cleanly.
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            logger.debug("complete: session_id=%s not found — no-op", session_id)
            return
        entry.admitted = False
        logger.debug("SessionRegistry: completed session=%s", session_id)

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(self, timeout: float, on_finalize: FinalizeCallback) -> None:
        """Graceful shutdown: finalize all in-flight sessions within *timeout*.

        Algorithm:
          1. Set draining flag — new admit() calls raise RuntimeError.
          2. Collect all in-flight sessions.
          3. Invoke on_finalize(session_id) concurrently for each, bounded by
             *timeout* seconds total.  Tasks that exceed the budget are cancelled
             (not awaited) to respect the hard timeout bound.
          4. Clear the in-flight set.

        Args:
            timeout:     Maximum seconds to wait for all finalizers (total budget).
            on_finalize: Async callable invoked once per in-flight session_id.
                         Must accept a single str argument.
        """
        self._draining = True
        sessions_to_drain = list(self.inflight)
        logger.info(
            "SessionRegistry: drain started, %d in-flight sessions, timeout=%.1fs",
            len(sessions_to_drain),
            timeout,
        )

        if sessions_to_drain:
            # Wrap in a coroutine so create_task always receives a Coroutine,
            # not the broader Awaitable returned by FinalizeCallback.
            async def _finalize(sid: str) -> None:
                await on_finalize(sid)

            tasks = [
                asyncio.create_task(_finalize(sid), name=f"drain-{sid}")
                for sid in sessions_to_drain
            ]
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                logger.warning(
                    "drain: %d finalizer(s) exceeded timeout=%.1fs — cancelling",
                    len(pending),
                    timeout,
                )
                for t in pending:
                    t.cancel()
                # Not awaited — blocking on a swallowed-cancel would violate the bound.

        # Clear in-flight state regardless of timeout outcome.
        for entry in self._sessions.values():
            entry.admitted = False

        logger.info(
            "SessionRegistry: drain complete, %d sessions finalized",
            len(sessions_to_drain),
        )


__all__ = ["RuntimeSessionRegistry"]
