"""Unit tests for ImportBasedCoverageAnalyzer — coverage mapping via import tracing."""

from __future__ import annotations

from swarmline.code_intel.coverage_checker import ImportBasedCoverageAnalyzer
from swarmline.code_intel.protocols import CoverageAnalyzerPort
from swarmline.code_intel.types import (
    CoverageMapping,
    ImportEdge,
    LanguageSeam,
    RepoMap,
    SymbolKind,
)


def _repo(
    files: tuple[str, ...],
    imports: tuple[ImportEdge, ...] = (),
) -> RepoMap:
    return RepoMap(root_path="/repo", files=files, symbols=(), imports=imports)


def _seam(file_path: str, signature: str) -> LanguageSeam:
    return LanguageSeam(
        file_path=file_path,
        line=1,
        kind=SymbolKind.FUNCTION,
        signature=signature,
        references_count=0,
    )


class TestImportBasedCoverageAnalyzerMapping:
    """Tests for test-to-seam mapping."""

    def test_map_coverage_test_imports_module_found(self) -> None:
        """test_utils.py imports utils -> covers seam in utils.py."""
        repo = _repo(
            files=("utils.py", "test_utils.py"),
            imports=(ImportEdge("test_utils.py", "utils", ("helper",)),),
        )
        seams = [_seam("utils.py", "def helper()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert "test_utils.py" in result.seam_to_tests["def helper()"]

    def test_map_coverage_no_tests_for_module_empty_list(self) -> None:
        """No test imports the module -> empty list."""
        repo = _repo(
            files=("utils.py", "test_other.py"),
            imports=(ImportEdge("test_other.py", "other", ("func",)),),
        )
        seams = [_seam("utils.py", "def helper()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert result.seam_to_tests["def helper()"] == ()

    def test_map_coverage_empty_seams_empty_mapping(self) -> None:
        """Empty seams -> empty mapping."""
        repo = _repo(files=("utils.py",))
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, [])

        assert result.seam_to_tests == {}

    def test_map_coverage_multiple_test_files_all_found(self) -> None:
        """Multiple test files import same module -> all listed."""
        repo = _repo(
            files=("utils.py", "test_utils.py", "test_integration.py"),
            imports=(
                ImportEdge("test_utils.py", "utils", ("a",)),
                ImportEdge("test_integration.py", "utils", ("b",)),
            ),
        )
        seams = [_seam("utils.py", "def helper()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert set(result.seam_to_tests["def helper()"]) == {
            "test_utils.py",
            "test_integration.py",
        }

    def test_map_coverage_multiple_seams_same_file(self) -> None:
        """Multiple seams from same file -> same test files for all."""
        repo = _repo(
            files=("utils.py", "test_utils.py"),
            imports=(ImportEdge("test_utils.py", "utils", ("a", "b")),),
        )
        seams = [
            _seam("utils.py", "def func_a()"),
            _seam("utils.py", "def func_b()"),
        ]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert result.seam_to_tests["def func_a()"] == ("test_utils.py",)
        assert result.seam_to_tests["def func_b()"] == ("test_utils.py",)


class TestImportBasedCoverageAnalyzerTestDetection:
    """Tests for test file detection patterns."""

    def test_detects_test_prefix_files(self) -> None:
        """Files matching test_*.py are detected as test files."""
        repo = _repo(
            files=("main.py", "test_main.py"),
            imports=(ImportEdge("test_main.py", "main", ("run",)),),
        )
        seams = [_seam("main.py", "def run()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert "test_main.py" in result.seam_to_tests["def run()"]

    def test_detects_test_suffix_files(self) -> None:
        """Files matching *_test.py are detected as test files."""
        repo = _repo(
            files=("main.py", "main_test.py"),
            imports=(ImportEdge("main_test.py", "main", ("run",)),),
        )
        seams = [_seam("main.py", "def run()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert "main_test.py" in result.seam_to_tests["def run()"]

    def test_non_test_file_not_counted_as_coverage(self) -> None:
        """Regular files that import module are NOT test coverage."""
        repo = _repo(
            files=("utils.py", "app.py"),
            imports=(ImportEdge("app.py", "utils", ("helper",)),),
        )
        seams = [_seam("utils.py", "def helper()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert result.seam_to_tests["def helper()"] == ()

    def test_nested_test_file_detected(self) -> None:
        """Test files in subdirectories are detected."""
        repo = _repo(
            files=("pkg/utils.py", "tests/test_utils.py"),
            imports=(ImportEdge("tests/test_utils.py", "pkg.utils", ("helper",)),),
        )
        seams = [_seam("pkg/utils.py", "def helper()")]
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, seams)

        assert "tests/test_utils.py" in result.seam_to_tests["def helper()"]


class TestImportBasedCoverageAnalyzerProtocol:
    """Verify ImportBasedCoverageAnalyzer satisfies CoverageAnalyzerPort."""

    def test_satisfies_coverage_analyzer_port(self) -> None:
        assert isinstance(ImportBasedCoverageAnalyzer(), CoverageAnalyzerPort)

    def test_returns_coverage_mapping_type(self) -> None:
        repo = _repo(files=())
        result = ImportBasedCoverageAnalyzer().map_coverage(repo, [])
        assert isinstance(result, CoverageMapping)
