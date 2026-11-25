"""Tests for InMemoryAuditTrail — append-only, thread-safe audit storage.

TDD: Red phase — tests written before implementation.
"""

from __future__ import annotations

import threading
import uuid

from swarmline.governance.audit_trail import InMemoryAuditTrail
from swarmline.governance.protocols import AuditTrailPort
from swarmline.governance.types import AuditEntry, AuditTrail


def _make_entry(
    run_id: str = "run-1",
    actor: str = "agent-1",
    action: str = "file_read",
    entry_id: str | None = None,
    tool_name: str | None = "read_file",
    file_path: str | None = "/src/main.py",
    decision: str | None = "allowed",
) -> AuditEntry:
    return AuditEntry(
        entry_id=entry_id or str(uuid.uuid4()),
        run_id=run_id,
        timestamp=1700000000.0,
        actor=actor,
        action=action,
        tool_name=tool_name,
        file_path=file_path,
        decision=decision,
        details={},
    )


class TestInMemoryAuditTrailProtocol:
    """InMemoryAuditTrail satisfies AuditTrailPort."""

    def test_satisfies_protocol(self) -> None:
        impl = InMemoryAuditTrail()
        assert isinstance(impl, AuditTrailPort)


class TestInMemoryAuditTrailRecord:
    """record() appends entries."""

    def test_record_single_entry(self) -> None:
        trail = InMemoryAuditTrail()
        entry = _make_entry()
        trail.record(entry)
        result = trail.get_trail("run-1")
        assert len(result.entries) == 1
        assert result.entries[0] is entry

    def test_record_multiple_entries_same_run(self) -> None:
        trail = InMemoryAuditTrail()
        e1 = _make_entry(entry_id="e-1", action="read")
        e2 = _make_entry(entry_id="e-2", action="write")
        trail.record(e1)
        trail.record(e2)
        result = trail.get_trail("run-1")
        assert len(result.entries) == 2

    def test_record_preserves_insertion_order(self) -> None:
        trail = InMemoryAuditTrail()
        entries = [
            _make_entry(entry_id=f"e-{i}", action=f"action-{i}") for i in range(5)
        ]
        for e in entries:
            trail.record(e)
        result = trail.get_trail("run-1")
        assert [e.action for e in result.entries] == [f"action-{i}" for i in range(5)]

    def test_record_different_runs_isolated(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(run_id="run-A", entry_id="a"))
        trail.record(_make_entry(run_id="run-B", entry_id="b"))
        assert len(trail.get_trail("run-A").entries) == 1
        assert len(trail.get_trail("run-B").entries) == 1


class TestInMemoryAuditTrailGetTrail:
    """get_trail() returns AuditTrail."""

    def test_returns_audit_trail_type(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry())
        result = trail.get_trail("run-1")
        assert isinstance(result, AuditTrail)

    def test_run_id_matches(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(run_id="my-run"))
        result = trail.get_trail("my-run")
        assert result.run_id == "my-run"

    def test_entries_are_tuple(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry())
        result = trail.get_trail("run-1")
        assert isinstance(result.entries, tuple)

    def test_unknown_run_returns_empty(self) -> None:
        trail = InMemoryAuditTrail()
        result = trail.get_trail("nonexistent")
        assert result.run_id == "nonexistent"
        assert result.entries == ()


class TestInMemoryAuditTrailGetEntriesByActor:
    """get_entries_by_actor() filters by actor."""

    def test_filters_by_actor(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(actor="alice", entry_id="a"))
        trail.record(_make_entry(actor="bob", entry_id="b"))
        trail.record(_make_entry(actor="alice", entry_id="c"))
        result = trail.get_entries_by_actor("run-1", "alice")
        assert len(result) == 2
        assert all(e.actor == "alice" for e in result)

    def test_returns_list(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(actor="alice"))
        result = trail.get_entries_by_actor("run-1", "alice")
        assert isinstance(result, list)

    def test_no_match_returns_empty(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(actor="alice"))
        result = trail.get_entries_by_actor("run-1", "unknown")
        assert result == []

    def test_wrong_run_returns_empty(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(run_id="run-1", actor="alice"))
        result = trail.get_entries_by_actor("run-2", "alice")
        assert result == []


class TestInMemoryAuditTrailAppendOnly:
    """Audit trail is append-only — no mutation of stored entries."""

    def test_get_trail_returns_new_tuple_each_call(self) -> None:
        trail = InMemoryAuditTrail()
        trail.record(_make_entry(entry_id="e-1"))
        t1 = trail.get_trail("run-1")
        trail.record(_make_entry(entry_id="e-2"))
        t2 = trail.get_trail("run-1")
        assert len(t1.entries) == 1
        assert len(t2.entries) == 2


class TestInMemoryAuditTrailThreadSafety:
    """Concurrent writes must not lose entries."""

    def test_concurrent_writes_no_lost_entries(self) -> None:
        trail = InMemoryAuditTrail()
        n_threads = 10
        entries_per_thread = 50

        def write_entries(thread_idx: int) -> None:
            for i in range(entries_per_thread):
                trail.record(
                    _make_entry(
                        entry_id=f"t{thread_idx}-e{i}",
                        actor=f"thread-{thread_idx}",
                    )
                )

        threads = [
            threading.Thread(target=write_entries, args=(t,)) for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = trail.get_trail("run-1")
        assert len(result.entries) == n_threads * entries_per_thread
