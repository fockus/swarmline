"""Tests for RuntimeSessionRegistry and StartupCrashDetector. TDD.

Covers:
  - admit/complete removes from inflight
  - drain calls on_finalize per inflight session and clears the set
  - admit emits heartbeat using injected clock timestamp
  - drain rejects subsequent admits
  - drain only finalizes admitted (not merely registered) sessions
  - complete on unknown session is a no-op
  - StartupCrashDetector: stale sessions flagged, fresh sessions not flagged
  - StartupCrashDetector.mark_crashed invokes callback and returns crashed set
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeHeartbeatEmitter:
    """Captures beat_now calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime]] = []

    async def beat_now(self, session_id: str, ts: datetime) -> None:
        self.calls.append((session_id, ts))


def _fixed_clock(ts: datetime) -> Callable[[], datetime]:
    def _now() -> datetime:
        return ts

    return _now


# ---------------------------------------------------------------------------
# RuntimeSessionRegistry tests
# ---------------------------------------------------------------------------


class TestRuntimeSessionRegistry:
    async def test_admit_then_complete_removes_from_inflight(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        # Act
        registry.register("s1", "owner-1")
        await registry.admit("s1")
        assert "s1" in registry.inflight

        registry.complete("s1")

        # Assert
        assert "s1" not in registry.inflight

    async def test_drain_calls_on_finalize_per_inflight_session(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        registry.register("s1", "owner-1")
        registry.register("s2", "owner-2")
        await registry.admit("s1")
        await registry.admit("s2")

        finalized: list[str] = []

        async def on_finalize(session_id: str) -> None:
            finalized.append(session_id)

        # Act
        await registry.drain(timeout=5.0, on_finalize=on_finalize)

        # Assert
        assert sorted(finalized) == ["s1", "s2"]

    async def test_drain_clears_inflight_after_finalize(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )
        registry.register("s1", "owner-1")
        await registry.admit("s1")

        async def on_finalize(session_id: str) -> None:
            pass

        # Act
        await registry.drain(timeout=5.0, on_finalize=on_finalize)

        # Assert
        assert len(registry.inflight) == 0

    async def test_admit_emits_heartbeat_with_injected_clock_timestamp(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        # Act
        registry.register("s1", "owner-x")
        await registry.admit("s1")

        # Assert — exactly one beat, correct session_id and injected timestamp
        assert len(emitter.calls) == 1
        called_session_id, called_ts = emitter.calls[0]
        assert called_session_id == "s1"
        assert called_ts == ts

    async def test_drain_rejects_subsequent_admits(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        async def on_finalize(session_id: str) -> None:
            pass

        await registry.drain(timeout=1.0, on_finalize=on_finalize)

        # Act — try to admit after drain started
        registry.register("s1", "owner-1")
        with pytest.raises(RuntimeError, match="draining"):
            await registry.admit("s1")

    async def test_drain_only_finalizes_admitted_sessions_not_merely_registered(
        self,
    ) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )
        registry.register("s1", "owner-1")  # registered only — not admitted

        finalized: list[str] = []

        async def on_finalize(session_id: str) -> None:
            finalized.append(session_id)

        # Act
        await registry.drain(timeout=1.0, on_finalize=on_finalize)

        # Assert — registered-but-not-admitted sessions are not finalized
        assert finalized == []

    async def test_complete_on_unknown_session_is_noop(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        # Act + Assert — must not raise
        registry.complete("nonexistent-session")

    async def test_owner_id_stored_on_register(self) -> None:
        # Arrange
        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = _FakeHeartbeatEmitter()
        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=emitter,
        )

        # Act
        registry.register("s1", "owner-acme")

        # Assert
        assert registry.owner_of("s1") == "owner-acme"

    async def test_admit_racing_drain_never_leaks_inflight_session(self) -> None:
        """Admit re-checks _draining after the heartbeat await.

        Race: admit suspends mid-heartbeat → drain runs (sets _draining=True,
        reads empty inflight, clears) → admit resumes.  Without the post-await
        re-check, entry.admitted would be set True after drain completed,
        leaking an in-flight session that was never finalized.
        """
        import asyncio

        from swarmline.hosting.session_registry import RuntimeSessionRegistry

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        started: asyncio.Event = asyncio.Event()
        release: asyncio.Event = asyncio.Event()

        class _BlockingEmitter:
            async def beat_now(self, session_id: str, ts_: datetime) -> None:
                started.set()
                await release.wait()

        registry = RuntimeSessionRegistry(
            now_factory=_fixed_clock(ts),
            heartbeat_emitter=_BlockingEmitter(),
        )

        finalized: list[str] = []

        async def on_finalize(sid: str) -> None:
            finalized.append(sid)

        registry.register("s1", "owner-1")
        admit_task = asyncio.create_task(registry.admit("s1"))

        # Wait until admit is suspended inside beat_now.
        await started.wait()

        # Drain: sets _draining=True, sees empty inflight (s1 not yet admitted),
        # finalizes nothing, clears (no-op), returns.
        await registry.drain(timeout=1.0, on_finalize=on_finalize)

        # Unblock the heartbeat so admit() resumes past the await.
        release.set()

        # Without the post-await re-check, admit would set entry.admitted=True → leak.
        # With the re-check, it raises RuntimeError.
        with pytest.raises(RuntimeError, match="draining"):
            await admit_task

        # Invariant: no in-flight session may exist after drain returns.
        assert registry.inflight == frozenset()


# ---------------------------------------------------------------------------
# StartupCrashDetector tests
# ---------------------------------------------------------------------------


class TestStartupCrashDetector:
    def test_stale_sessions_flagged_when_heartbeat_before_threshold(self) -> None:
        # Arrange
        from swarmline.hosting.crash_detector import StartupCrashDetector

        old_ts = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
        threshold = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        fresh_ts = datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)

        detector = StartupCrashDetector(
            heartbeats={
                "stale-s1": old_ts,
                "stale-s2": old_ts,
                "fresh-s3": fresh_ts,
            }
        )

        # Act
        flagged = detector.detect_stale(threshold)
        flagged_ids = {entry.session_id for entry in flagged}

        # Assert
        assert "stale-s1" in flagged_ids
        assert "stale-s2" in flagged_ids
        assert "fresh-s3" not in flagged_ids

    def test_fresh_sessions_not_flagged(self) -> None:
        # Arrange
        from swarmline.hosting.crash_detector import StartupCrashDetector

        fresh_ts = datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)
        threshold = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        detector = StartupCrashDetector(heartbeats={"fresh-s1": fresh_ts})

        # Act
        flagged = detector.detect_stale(threshold)

        # Assert
        assert flagged == []

    def test_mark_crashed_invokes_on_crash_for_stale_sessions(self) -> None:
        # Arrange
        from swarmline.hosting.crash_detector import StartupCrashDetector

        old_ts = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
        threshold = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        detector = StartupCrashDetector(
            heartbeats={
                "stale-s1": old_ts,
                "fresh-s2": datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC),
            }
        )

        crashed: set[str] = set()
        # Act
        crashed_ids = detector.mark_crashed(
            threshold, on_crash=lambda sid: crashed.add(sid)
        )

        # Assert
        assert crashed == {"stale-s1"}
        assert crashed_ids == {"stale-s1"}

    def test_empty_heartbeats_returns_empty_flagged_list(self) -> None:
        # Arrange
        from swarmline.hosting.crash_detector import StartupCrashDetector

        threshold = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        detector = StartupCrashDetector(heartbeats={})

        # Act + Assert
        assert detector.detect_stale(threshold) == []

    def test_session_exactly_at_threshold_is_not_flagged(self) -> None:
        # Arrange — boundary: ts == threshold is NOT stale (strictly less-than)
        from swarmline.hosting.crash_detector import StartupCrashDetector

        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        detector = StartupCrashDetector(heartbeats={"border-s1": ts})

        # Act
        flagged = detector.detect_stale(threshold=ts)

        # Assert — exactly at threshold is NOT flagged
        assert flagged == []
