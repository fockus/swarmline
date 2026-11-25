"""Contract tests for CoverageAnalyzerPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing map_coverage should pass.
"""

from __future__ import annotations

from swarmline.code_intel.protocols import CoverageAnalyzerPort
from swarmline.code_intel.types import (
    CoverageMapping,
    LanguageSeam,
    RepoMap,
    SymbolKind,
)


class _StubCoverageAnalyzer:
    """Minimal valid implementation for contract testing."""

    def map_coverage(
        self, repo_map: RepoMap, seams: list[LanguageSeam]
    ) -> CoverageMapping:
        mapping: dict[str, tuple[str, ...]] = {}
        for seam in seams:
            mapping[seam.signature] = (f"tests/test_{seam.file_path}",)
        return CoverageMapping(seam_to_tests=mapping)


class _InvalidCoverageAnalyzer:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


_EMPTY_MAP = RepoMap(root_path="/repo", files=(), symbols=(), imports=())

_SAMPLE_SEAMS = [
    LanguageSeam(
        file_path="main.py",
        line=1,
        kind=SymbolKind.FUNCTION,
        signature="def main() -> None",
        references_count=2,
    ),
    LanguageSeam(
        file_path="utils.py",
        line=5,
        kind=SymbolKind.CLASS,
        signature="class Helper",
        references_count=4,
    ),
]


class TestCoverageAnalyzerPortContract:
    """CoverageAnalyzerPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubCoverageAnalyzer()
        assert isinstance(impl, CoverageAnalyzerPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidCoverageAnalyzer()
        assert not isinstance(invalid, CoverageAnalyzerPort)

    def test_map_coverage_returns_coverage_mapping(self) -> None:
        impl = _StubCoverageAnalyzer()
        result = impl.map_coverage(_EMPTY_MAP, _SAMPLE_SEAMS)
        assert isinstance(result, CoverageMapping)

    def test_map_coverage_seam_to_tests_is_dict(self) -> None:
        impl = _StubCoverageAnalyzer()
        result = impl.map_coverage(_EMPTY_MAP, _SAMPLE_SEAMS)
        assert isinstance(result.seam_to_tests, dict)

    def test_map_coverage_keys_are_seam_signatures(self) -> None:
        impl = _StubCoverageAnalyzer()
        result = impl.map_coverage(_EMPTY_MAP, _SAMPLE_SEAMS)
        for seam in _SAMPLE_SEAMS:
            assert seam.signature in result.seam_to_tests

    def test_map_coverage_values_are_tuples_of_str(self) -> None:
        impl = _StubCoverageAnalyzer()
        result = impl.map_coverage(_EMPTY_MAP, _SAMPLE_SEAMS)
        for test_files in result.seam_to_tests.values():
            assert isinstance(test_files, tuple)
            assert all(isinstance(f, str) for f in test_files)

    def test_map_coverage_empty_seams_returns_empty(self) -> None:
        impl = _StubCoverageAnalyzer()
        result = impl.map_coverage(_EMPTY_MAP, [])
        assert isinstance(result, CoverageMapping)
        assert result.seam_to_tests == {}
