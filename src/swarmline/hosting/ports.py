"""Protocols for the hosting session-lifecycle subpackage.

Generic, product-neutral ports:
  - ClockFactory: injectable clock for deterministic testing.
  - HeartbeatEmitter: ISP-compliant protocol (1 method) for recording session liveness.
  - FinalizeCallback: async callable invoked per session during drain.

No tenant/workspace/AccessContext/FastAPI/SQLAlchemy/Lobu types appear here.
All session identifiers are plain str.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

# Injected clock factory — returns the "current" time.
# Inject a fixed-clock lambda in tests for deterministic assertions.
ClockFactory = Callable[[], datetime]

# Async callback invoked once per in-flight session during drain.
# Receives the session_id string; returns Awaitable[None].
FinalizeCallback = Callable[[str], Awaitable[None]]


@runtime_checkable
class HeartbeatEmitter(Protocol):
    """ISP-compliant heartbeat emitter — 1 method.

    Implementations record a liveness timestamp for the given session_id.
    The injected clock supplies the timestamp so callers remain deterministic.

    Typical implementations:
      - In-memory recorder (tests): appends (session_id, ts) to a list.
      - Persistent store (production): writes a heartbeat row to the DB.
    """

    async def beat_now(self, session_id: str, ts: datetime) -> None:
        """Record a liveness heartbeat for *session_id* at timestamp *ts*.

        Args:
            session_id: Generic string identifier for the session.
            ts:         Timestamp supplied by the caller's injected clock.

        Raises:
            Exception: re-raised on write failure so the caller can clean up.
        """
        ...


__all__ = [
    "ClockFactory",
    "FinalizeCallback",
    "HeartbeatEmitter",
]
