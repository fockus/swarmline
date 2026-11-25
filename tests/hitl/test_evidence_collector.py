"""Tests for InMemoryEvidenceCollector.

TDD: these tests were written BEFORE the implementation.
"""

from __future__ import annotations

import pytest
from swarmline.hitl.hitl_protocols import EvidenceSurfacePort
from swarmline.hitl.timeline_types import EvidenceSurface


@pytest.fixture()
def collector() -> EvidenceSurfacePort:
    from swarmline.hitl.evidence_collector import InMemoryEvidenceCollector

    return InMemoryEvidenceCollector()


class TestInMemoryEvidenceCollector:
    """InMemoryEvidenceCollector implementation tests."""

    def test_satisfies_protocol(self, collector: EvidenceSurfacePort) -> None:
        assert isinstance(collector, EvidenceSurfacePort)

    def test_collect_evidence_returns_evidence_surface(
        self, collector: EvidenceSurfacePort
    ) -> None:
        result = collector.collect_evidence("run-1")
        assert isinstance(result, EvidenceSurface)
        assert result.run_id == "run-1"

    def test_collect_evidence_with_all_fields(
        self, collector: EvidenceSurfacePort
    ) -> None:
        result = collector.collect_evidence(
            "run-1",
            test_results=("PASS: test_a", "FAIL: test_b"),
            logs=("INFO: started", "ERROR: crash"),
            artifacts=("report.html",),
            changed_files=("src/main.py", "src/utils.py"),
            plan_state="step-3-complete",
        )
        assert result.test_results == ("PASS: test_a", "FAIL: test_b")
        assert result.logs == ("INFO: started", "ERROR: crash")
        assert result.artifacts == ("report.html",)
        assert result.changed_files == ("src/main.py", "src/utils.py")
        assert result.plan_state == "step-3-complete"

    def test_collect_evidence_defaults_to_empty(
        self, collector: EvidenceSurfacePort
    ) -> None:
        result = collector.collect_evidence("run-1")
        assert result.test_results == ()
        assert result.logs == ()
        assert result.artifacts == ()
        assert result.changed_files == ()
        assert result.plan_state is None

    def test_get_evidence_returns_collected(
        self, collector: EvidenceSurfacePort
    ) -> None:
        collector.collect_evidence("run-1", test_results=("PASS",))
        result = collector.get_evidence("run-1")
        assert result is not None
        assert result.test_results == ("PASS",)

    def test_get_evidence_unknown_run_returns_none(
        self, collector: EvidenceSurfacePort
    ) -> None:
        assert collector.get_evidence("nonexistent") is None

    def test_collect_evidence_overwrites_previous(
        self, collector: EvidenceSurfacePort
    ) -> None:
        collector.collect_evidence("run-1", test_results=("old",))
        collector.collect_evidence("run-1", test_results=("new",))
        result = collector.get_evidence("run-1")
        assert result is not None
        assert result.test_results == ("new",)

    def test_multiple_runs_stored_independently(
        self, collector: EvidenceSurfacePort
    ) -> None:
        collector.collect_evidence("run-1", test_results=("A",))
        collector.collect_evidence("run-2", test_results=("B",))
        r1 = collector.get_evidence("run-1")
        r2 = collector.get_evidence("run-2")
        assert r1 is not None and r1.test_results == ("A",)
        assert r2 is not None and r2.test_results == ("B",)

    def test_evidence_tuples_are_immutable(
        self, collector: EvidenceSurfacePort
    ) -> None:
        ev = collector.collect_evidence(
            "run-1",
            test_results=("PASS",),
            logs=("log",),
            artifacts=("art",),
            changed_files=("f",),
        )
        assert isinstance(ev.test_results, tuple)
        assert isinstance(ev.logs, tuple)
        assert isinstance(ev.artifacts, tuple)
        assert isinstance(ev.changed_files, tuple)
