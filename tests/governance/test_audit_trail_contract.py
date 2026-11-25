"""Contract tests for AuditTrailPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing record + get_trail + get_entries_by_actor should pass.
"""

from __future__ import annotations

from swarmline.governance.protocols import AuditTrailPort
from swarmline.governance.types import (
    AuditEntry,
    AuditTrail,
)


class _StubAuditTrail:
    """Minimal valid implementation for contract testing."""

    def __init__(self) -> None:
        self._entries: dict[str, list[AuditEntry]] = {}

    def record(self, entry: AuditEntry) -> None:
        self._entries.setdefault(entry.run_id, []).append(entry)

    def get_trail(self, run_id: str) -> AuditTrail:
        entries = self._entries.get(run_id, [])
        return AuditTrail(run_id=run_id, entries=tuple(entries))

    def get_entries_by_actor(self, run_id: str, actor: str) -> list[AuditEntry]:
        entries = self._entries.get(run_id, [])
        return [e for e in entries if e.actor == actor]


class _InvalidAuditTrail:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


def _make_entry(
    run_id: str = "run-1",
    actor: str = "agent-1",
    action: str = "file_read",
) -> AuditEntry:
    return AuditEntry(
        entry_id="e-1",
        run_id=run_id,
        timestamp=1700000000.0,
        actor=actor,
        action=action,
        tool_name="read_file",
        file_path="/src/main.py",
        decision="allowed",
        details={},
    )


class TestAuditTrailPortContract:
    """AuditTrailPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubAuditTrail()
        assert isinstance(impl, AuditTrailPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidAuditTrail()
        assert not isinstance(invalid, AuditTrailPort)

    def test_record_accepts_audit_entry(self) -> None:
        impl = _StubAuditTrail()
        entry = _make_entry()
        impl.record(entry)

    def test_get_trail_returns_audit_trail(self) -> None:
        impl = _StubAuditTrail()
        entry = _make_entry()
        impl.record(entry)
        trail = impl.get_trail("run-1")
        assert isinstance(trail, AuditTrail)
        assert trail.run_id == "run-1"

    def test_get_trail_entries_are_tuple(self) -> None:
        impl = _StubAuditTrail()
        impl.record(_make_entry())
        trail = impl.get_trail("run-1")
        assert isinstance(trail.entries, tuple)
        assert all(isinstance(e, AuditEntry) for e in trail.entries)

    def test_get_trail_empty_run_returns_empty_entries(self) -> None:
        impl = _StubAuditTrail()
        trail = impl.get_trail("nonexistent")
        assert trail.entries == ()

    def test_get_entries_by_actor_returns_list(self) -> None:
        impl = _StubAuditTrail()
        impl.record(_make_entry(actor="alice"))
        impl.record(_make_entry(actor="bob"))
        result = impl.get_entries_by_actor("run-1", "alice")
        assert isinstance(result, list)
        assert all(e.actor == "alice" for e in result)

    def test_get_entries_by_actor_no_match_empty(self) -> None:
        impl = _StubAuditTrail()
        impl.record(_make_entry(actor="alice"))
        result = impl.get_entries_by_actor("run-1", "unknown")
        assert result == []


class TestAuditEntryFrozen:
    """AuditEntry and AuditTrail are frozen dataclasses."""

    def test_entry_is_frozen(self) -> None:
        entry = _make_entry()
        try:
            entry.actor = "changed"  # type: ignore[misc]
            raise AssertionError("Should have raised")  # noqa: TRY301
        except (AttributeError, TypeError):
            pass

    def test_entry_fields(self) -> None:
        entry = _make_entry()
        assert entry.entry_id == "e-1"
        assert entry.run_id == "run-1"
        assert isinstance(entry.timestamp, float)
        assert entry.actor == "agent-1"
        assert entry.action == "file_read"
        assert entry.tool_name == "read_file"
        assert entry.file_path == "/src/main.py"
        assert entry.decision == "allowed"
        assert isinstance(entry.details, dict)

    def test_trail_is_frozen(self) -> None:
        trail = AuditTrail(run_id="r", entries=())
        try:
            trail.run_id = "changed"  # type: ignore[misc]
            raise AssertionError("Should have raised")  # noqa: TRY301
        except (AttributeError, TypeError):
            pass
