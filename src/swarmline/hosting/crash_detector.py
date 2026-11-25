"""StartupCrashDetector — detect stale sessions at process startup.

Ported from taskloom's crash-recovery scan (SessionRehydrator /
sql_heartbeat_repository stale query) and generalised:
  - NO tenant/workspace/AccessContext/FastAPI/SQLAlchemy/Lobu.
  - Heartbeat map is plain dict[str, datetime] — caller supplies it from
    any storage backend (SQL, Redis, in-memory).
  - Finalize is a plain Callable[[str], None] — no product service coupling.

Design:
  detect_stale(threshold)             — returns StaleSession entries for
                                        sessions whose last heartbeat
                                        predates *threshold*.
  mark_crashed(threshold, on_crash)   — calls on_crash(session_id) for every
                                        stale session and returns the crashed set.

The detector is stateless after construction — call it multiple times with
different thresholds if needed (e.g. different staleness windows per tier).

REQ-OSS-050: opt-in / additive.
REQ-OSS-051: zero product coupling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StaleSession:
    """Immutable record of a session whose last heartbeat predates the threshold."""

    session_id: str
    last_heartbeat: datetime


class StartupCrashDetector:
    """Detects sessions whose last heartbeat is older than a given threshold.

    Typical usage at process startup:
        heartbeats = await heartbeat_store.load_all()   # {session_id: ts}
        threshold  = now - timedelta(seconds=stale_seconds)
        detector   = StartupCrashDetector(heartbeats)
        crashed    = detector.mark_crashed(threshold, on_crash=mark_crashed_in_db)

    Args:
        heartbeats: Mapping of session_id → last heartbeat datetime.
                    Datetimes should be tz-aware (UTC) for correct comparison;
                    naive datetimes are accepted but the caller must ensure
                    consistent tz semantics with the supplied *threshold*.
    """

    def __init__(self, heartbeats: dict[str, datetime]) -> None:
        self._heartbeats: dict[str, datetime] = dict(heartbeats)

    def detect_stale(self, threshold: datetime) -> list[StaleSession]:
        """Return sessions whose last heartbeat strictly predates *threshold*.

        A session heartbeated exactly at *threshold* is NOT considered stale
        (strictly less-than comparison), matching the "X seconds of inactivity"
        semantic: at the boundary the session is just barely alive.

        Args:
            threshold: Sessions with last_heartbeat < threshold are flagged.

        Returns:
            List of StaleSession records (may be empty).
        """
        return [
            StaleSession(session_id=sid, last_heartbeat=ts)
            for sid, ts in self._heartbeats.items()
            if ts < threshold
        ]

    def mark_crashed(
        self,
        threshold: datetime,
        on_crash: Callable[[str], None],
    ) -> set[str]:
        """Flag all stale sessions and invoke *on_crash* for each.

        Args:
            threshold: Staleness boundary — see detect_stale().
            on_crash:  Synchronous callback called once per stale session_id.
                       Typical implementation: mark the session row CRASHED in DB.

        Returns:
            Set of session_ids that were flagged (same as
            {entry.session_id for entry in detect_stale(threshold)}).
        """
        stale = self.detect_stale(threshold)
        crashed: set[str] = set()
        for entry in stale:
            on_crash(entry.session_id)
            crashed.add(entry.session_id)
        return crashed


__all__ = ["StartupCrashDetector", "StaleSession"]
