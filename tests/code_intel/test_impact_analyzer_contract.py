"""Contract tests for ImpactAnalyzerPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing analyze_impact should pass.
"""

from __future__ import annotations

from swarmline.code_intel.protocols import ImpactAnalyzerPort
from swarmline.code_intel.types import (
    ImpactResult,
    RepoMap,
)


class _StubImpactAnalyzer:
    """Minimal valid implementation for contract testing."""

    def analyze_impact(self, repo_map: RepoMap, target_files: set[str]) -> ImpactResult:
        return ImpactResult(
            target_files=tuple(sorted(target_files)),
            directly_affected=("dep.py",),
            transitively_affected=("transitive.py",),
            blast_radius_score=0.25,
        )


class _InvalidImpactAnalyzer:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


_EMPTY_MAP = RepoMap(root_path="/repo", files=(), symbols=(), imports=())


class TestImpactAnalyzerPortContract:
    """ImpactAnalyzerPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubImpactAnalyzer()
        assert isinstance(impl, ImpactAnalyzerPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidImpactAnalyzer()
        assert not isinstance(invalid, ImpactAnalyzerPort)

    def test_analyze_impact_returns_impact_result(self) -> None:
        impl = _StubImpactAnalyzer()
        result = impl.analyze_impact(_EMPTY_MAP, {"main.py"})
        assert isinstance(result, ImpactResult)

    def test_analyze_impact_target_files_match_input(self) -> None:
        impl = _StubImpactAnalyzer()
        targets = {"a.py", "b.py"}
        result = impl.analyze_impact(_EMPTY_MAP, targets)
        assert set(result.target_files) == targets

    def test_analyze_impact_directly_affected_is_tuple(self) -> None:
        impl = _StubImpactAnalyzer()
        result = impl.analyze_impact(_EMPTY_MAP, {"main.py"})
        assert isinstance(result.directly_affected, tuple)

    def test_analyze_impact_transitively_affected_is_tuple(self) -> None:
        impl = _StubImpactAnalyzer()
        result = impl.analyze_impact(_EMPTY_MAP, {"main.py"})
        assert isinstance(result.transitively_affected, tuple)

    def test_analyze_impact_blast_radius_is_float(self) -> None:
        impl = _StubImpactAnalyzer()
        result = impl.analyze_impact(_EMPTY_MAP, {"main.py"})
        assert isinstance(result.blast_radius_score, float)
        assert 0.0 <= result.blast_radius_score <= 1.0
