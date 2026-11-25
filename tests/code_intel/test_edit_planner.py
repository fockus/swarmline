"""Unit tests for EditPlanner — TDD red phase first.

Tests cover: impact delegation, seam finding, coverage mapping,
dependency-based file ordering, test command suggestions.
"""

from __future__ import annotations

import pytest

from swarmline.code_intel.types import (
    CoverageMapping,
    EditPlan,
    ImpactResult,
    ImportEdge,
    LanguageSeam,
    RepoMap,
    SymbolInfo,
    SymbolKind,
)


# ── Fixtures ───────────────────────────────────────────────────────────


def _make_repo_map() -> RepoMap:
    """Sample repo with 3 files and import chain: app -> service -> models."""
    return RepoMap(
        root_path="/repo",
        files=("/repo/app.py", "/repo/service.py", "/repo/models.py"),
        symbols=(
            SymbolInfo("App", SymbolKind.CLASS, "/repo/app.py", 1, "class App"),
            SymbolInfo("run", SymbolKind.FUNCTION, "/repo/service.py", 1, "def run()"),
            SymbolInfo("User", SymbolKind.CLASS, "/repo/models.py", 1, "class User"),
        ),
        imports=(
            ImportEdge("/repo/app.py", "service", ("run",)),
            ImportEdge("/repo/service.py", "models", ("User",)),
        ),
    )


class _StubImpactAnalyzer:
    def analyze_impact(self, repo_map: RepoMap, target_files: set[str]) -> ImpactResult:
        return ImpactResult(
            target_files=tuple(sorted(target_files)),
            directly_affected=("/repo/service.py",),
            transitively_affected=("/repo/app.py",),
            blast_radius_score=0.67,
        )


class _StubCoverageAnalyzer:
    def map_coverage(
        self, repo_map: RepoMap, seams: list[LanguageSeam]
    ) -> CoverageMapping:
        mapping = {seam.signature: ["tests/test_models.py"] for seam in seams}
        return CoverageMapping(seam_to_tests=mapping)


class _StubLanguageParser:
    @property
    def supported_extensions(self) -> set[str]:
        return {".py"}

    def find_seams(self, file_path: str) -> list[LanguageSeam]:
        return [
            LanguageSeam(
                file_path=file_path,
                line=1,
                kind=SymbolKind.FUNCTION,
                signature=f"def stub_{file_path.split('/')[-1].replace('.py', '')}()",
                references_count=1,
            ),
        ]


@pytest.fixture()
def repo_map() -> RepoMap:
    return _make_repo_map()


@pytest.fixture()
def impact_analyzer() -> _StubImpactAnalyzer:
    return _StubImpactAnalyzer()


@pytest.fixture()
def coverage_analyzer() -> _StubCoverageAnalyzer:
    return _StubCoverageAnalyzer()


@pytest.fixture()
def language_parser() -> _StubLanguageParser:
    return _StubLanguageParser()


# ── Tests ──────────────────────────────────────────────────────────────


class TestEditPlanner:
    def test_plan_edit_returns_edit_plan(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        assert isinstance(result, EditPlan)

    def test_plan_edit_target_files_match_input(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        assert "/repo/models.py" in result.target_files

    def test_plan_edit_impact_is_impact_result(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        assert isinstance(result.impact, ImpactResult)
        assert result.impact.blast_radius_score == pytest.approx(0.67)

    def test_plan_edit_ordered_files_dependencies_first(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        # models.py (target, no deps) should come before service.py (imports models)
        # service.py should come before app.py (imports service)
        ordered = list(result.ordered_edit_files)
        assert len(ordered) >= 1
        if "/repo/models.py" in ordered and "/repo/service.py" in ordered:
            assert ordered.index("/repo/models.py") < ordered.index("/repo/service.py")

    def test_plan_edit_has_coverage(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        assert result.coverage is not None
        assert isinstance(result.coverage, CoverageMapping)

    def test_plan_edit_suggested_test_commands_not_empty(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        coverage_analyzer: _StubCoverageAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=coverage_analyzer,
            language_parser=language_parser,
        )
        assert len(result.suggested_test_commands) > 0

    def test_plan_edit_without_coverage_analyzer(
        self,
        repo_map: RepoMap,
        impact_analyzer: _StubImpactAnalyzer,
        language_parser: _StubLanguageParser,
    ) -> None:
        from swarmline.code_intel.edit_planner import plan_edit

        result = plan_edit(
            target_files={"/repo/models.py"},
            repo_map=repo_map,
            impact_analyzer=impact_analyzer,
            coverage_analyzer=None,
            language_parser=language_parser,
        )
        assert result.coverage is None
