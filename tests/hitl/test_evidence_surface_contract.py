"""Contract tests for EvidenceSurfacePort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing collect_evidence + get_evidence should pass.
"""

from __future__ import annotations


from swarmline.hitl.timeline_types import EvidenceSurface
from swarmline.hitl.hitl_protocols import EvidenceSurfacePort


class _StubEvidenceSurface:
    """Minimal valid implementation for contract testing."""

    def __init__(self) -> None:
        self._evidence: dict[str, EvidenceSurface] = {}

    def collect_evidence(
        self,
        run_id: str,
        *,
        test_results: tuple[str, ...] = (),
        logs: tuple[str, ...] = (),
        artifacts: tuple[str, ...] = (),
        changed_files: tuple[str, ...] = (),
        plan_state: str | None = None,
    ) -> EvidenceSurface:
        ev = EvidenceSurface(
            run_id=run_id,
            test_results=test_results,
            logs=logs,
            artifacts=artifacts,
            changed_files=changed_files,
            plan_state=plan_state,
        )
        self._evidence[run_id] = ev
        return ev

    def get_evidence(self, run_id: str) -> EvidenceSurface | None:
        return self._evidence.get(run_id)


class _InvalidEvidenceSurface:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestEvidenceSurfacePortContract:
    """EvidenceSurfacePort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubEvidenceSurface()
        assert isinstance(impl, EvidenceSurfacePort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidEvidenceSurface()
        assert not isinstance(invalid, EvidenceSurfacePort)

    def test_collect_evidence_returns_evidence_surface(self) -> None:
        impl = _StubEvidenceSurface()
        result = impl.collect_evidence("run-1")
        assert isinstance(result, EvidenceSurface)

    def test_collect_evidence_run_id_matches(self) -> None:
        impl = _StubEvidenceSurface()
        result = impl.collect_evidence("run-42")
        assert result.run_id == "run-42"

    def test_get_evidence_returns_collected(self) -> None:
        impl = _StubEvidenceSurface()
        impl.collect_evidence("run-1", test_results=("PASS: test_a",))
        result = impl.get_evidence("run-1")
        assert result is not None
        assert result.test_results == ("PASS: test_a",)

    def test_get_evidence_unknown_run_returns_none(self) -> None:
        impl = _StubEvidenceSurface()
        assert impl.get_evidence("nonexistent") is None

    def test_evidence_tuples_are_immutable(self) -> None:
        impl = _StubEvidenceSurface()
        ev = impl.collect_evidence(
            "run-1",
            test_results=("PASS",),
            logs=("log line",),
            artifacts=("report.html",),
            changed_files=("src/main.py",),
        )
        assert isinstance(ev.test_results, tuple)
        assert isinstance(ev.logs, tuple)
        assert isinstance(ev.artifacts, tuple)
        assert isinstance(ev.changed_files, tuple)

    def test_collect_evidence_with_plan_state(self) -> None:
        impl = _StubEvidenceSurface()
        ev = impl.collect_evidence("run-1", plan_state="step-3-complete")
        assert ev.plan_state == "step-3-complete"

    def test_collect_evidence_defaults_to_empty(self) -> None:
        impl = _StubEvidenceSurface()
        ev = impl.collect_evidence("run-1")
        assert ev.test_results == ()
        assert ev.logs == ()
        assert ev.artifacts == ()
        assert ev.changed_files == ()
        assert ev.plan_state is None
