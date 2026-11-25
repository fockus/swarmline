"""Unit tests for GraphImpactAnalyzer — BFS-based blast radius analysis."""

from __future__ import annotations

from swarmline.code_intel.impact_analyzer import GraphImpactAnalyzer
from swarmline.code_intel.protocols import ImpactAnalyzerPort
from swarmline.code_intel.types import ImpactResult, ImportEdge, RepoMap


def _repo(
    files: tuple[str, ...],
    imports: tuple[ImportEdge, ...] = (),
) -> RepoMap:
    return RepoMap(root_path="/repo", files=files, symbols=(), imports=imports)


class TestGraphImpactAnalyzerDirect:
    """Tests for direct impact calculation."""

    def test_analyze_impact_single_import_directly_affected(self) -> None:
        """A imports B -> changing B directly affects A."""
        repo = _repo(
            files=("a.py", "b.py"),
            imports=(ImportEdge("a.py", "b", ("func",)),),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"b.py"})

        assert "a.py" in result.directly_affected
        assert set(result.target_files) == {"b.py"}

    def test_analyze_impact_no_dependents_empty_affected(self) -> None:
        """File with no importers -> empty affected sets."""
        repo = _repo(
            files=("a.py", "b.py"),
            imports=(ImportEdge("a.py", "b", ("func",)),),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"a.py"})

        assert result.directly_affected == ()
        assert result.transitively_affected == ()

    def test_analyze_impact_multiple_direct_dependents(self) -> None:
        """Multiple files import target -> all in directly_affected."""
        repo = _repo(
            files=("a.py", "b.py", "c.py"),
            imports=(
                ImportEdge("a.py", "c", ("x",)),
                ImportEdge("b.py", "c", ("y",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"c.py"})

        assert set(result.directly_affected) == {"a.py", "b.py"}

    def test_analyze_impact_target_not_imported_empty_affected(self) -> None:
        """Target file not referenced by any import -> empty."""
        repo = _repo(
            files=("a.py", "b.py", "isolated.py"),
            imports=(ImportEdge("a.py", "b", ("x",)),),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"isolated.py"})

        assert result.directly_affected == ()
        assert result.transitively_affected == ()


class TestGraphImpactAnalyzerTransitive:
    """Tests for transitive impact through chains."""

    def test_analyze_impact_chain_a_b_c_transitive(self) -> None:
        """A->B->C: changing C affects B directly, A transitively."""
        repo = _repo(
            files=("a.py", "b.py", "c.py"),
            imports=(
                ImportEdge("a.py", "b", ("func",)),
                ImportEdge("b.py", "c", ("cls",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"c.py"})

        assert "b.py" in result.directly_affected
        assert "a.py" in result.transitively_affected
        assert "a.py" not in result.directly_affected

    def test_analyze_impact_circular_import_no_infinite_loop(self) -> None:
        """A->B->A: circular import handled via visited set."""
        repo = _repo(
            files=("a.py", "b.py"),
            imports=(
                ImportEdge("a.py", "b", ("x",)),
                ImportEdge("b.py", "a", ("y",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"a.py"})

        assert "b.py" in result.directly_affected
        assert "a.py" not in result.directly_affected
        assert "a.py" not in result.transitively_affected

    def test_analyze_impact_deep_chain_four_levels(self) -> None:
        """A->B->C->D: changing D, B/C direct or transitive, A transitive."""
        repo = _repo(
            files=("a.py", "b.py", "c.py", "d.py"),
            imports=(
                ImportEdge("a.py", "b", ("x",)),
                ImportEdge("b.py", "c", ("y",)),
                ImportEdge("c.py", "d", ("z",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"d.py"})

        assert "c.py" in result.directly_affected
        assert "b.py" in result.transitively_affected
        assert "a.py" in result.transitively_affected

    def test_analyze_impact_diamond_dependency(self) -> None:
        """A->C, B->C, A->B: changing C, A and B directly affected."""
        repo = _repo(
            files=("a.py", "b.py", "c.py"),
            imports=(
                ImportEdge("a.py", "c", ("x",)),
                ImportEdge("b.py", "c", ("y",)),
                ImportEdge("a.py", "b", ("z",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"c.py"})

        assert set(result.directly_affected) == {"a.py", "b.py"}


class TestGraphImpactAnalyzerBlastRadius:
    """Tests for blast_radius_score calculation."""

    def test_blast_radius_score_correct_value(self) -> None:
        """blast_radius_score = len(all_affected) / len(files)."""
        repo = _repo(
            files=("a.py", "b.py", "c.py", "d.py"),
            imports=(
                ImportEdge("a.py", "d", ("x",)),
                ImportEdge("b.py", "d", ("y",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"d.py"})

        all_affected = len(result.directly_affected) + len(result.transitively_affected)
        assert result.blast_radius_score == all_affected / 4

    def test_blast_radius_empty_repo_returns_zero(self) -> None:
        """Empty repo -> score 0.0."""
        repo = _repo(files=(), imports=())
        result = GraphImpactAnalyzer().analyze_impact(repo, set())

        assert result.blast_radius_score == 0.0

    def test_blast_radius_always_between_zero_and_one(self) -> None:
        """Score is always in [0.0, 1.0]."""
        repo = _repo(
            files=("a.py", "b.py", "c.py"),
            imports=(
                ImportEdge("a.py", "b", ("x",)),
                ImportEdge("b.py", "c", ("y",)),
            ),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"c.py"})

        assert 0.0 <= result.blast_radius_score <= 1.0

    def test_blast_radius_all_files_affected(self) -> None:
        """All non-target files affected -> score close to 1.0."""
        repo = _repo(
            files=("a.py", "b.py"),
            imports=(ImportEdge("a.py", "b", ("x",)),),
        )
        result = GraphImpactAnalyzer().analyze_impact(repo, {"b.py"})

        assert result.blast_radius_score == 0.5  # 1 affected / 2 total


class TestGraphImpactAnalyzerProtocol:
    """Verify GraphImpactAnalyzer satisfies ImpactAnalyzerPort."""

    def test_satisfies_impact_analyzer_port(self) -> None:
        assert isinstance(GraphImpactAnalyzer(), ImpactAnalyzerPort)

    def test_returns_impact_result_type(self) -> None:
        repo = _repo(files=("a.py",), imports=())
        result = GraphImpactAnalyzer().analyze_impact(repo, {"a.py"})
        assert isinstance(result, ImpactResult)
