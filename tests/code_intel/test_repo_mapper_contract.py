"""Contract tests for RepoMapperPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing scan_repo + scan_file should pass.
"""

from __future__ import annotations

import pytest

from swarmline.code_intel.protocols import RepoMapperPort
from swarmline.code_intel.types import (
    ImportEdge,
    RepoMap,
    SymbolInfo,
    SymbolKind,
)


class _StubRepoMapper:
    """Minimal valid implementation for contract testing."""

    def scan_repo(self, root: str, extensions: set[str]) -> RepoMap:
        return RepoMap(
            root_path=root,
            files=("main.py",),
            symbols=(
                SymbolInfo(
                    name="main",
                    kind=SymbolKind.FUNCTION,
                    file_path="main.py",
                    line=1,
                    signature="def main() -> None",
                ),
            ),
            imports=(
                ImportEdge(
                    source_file="main.py",
                    target_module="os",
                    imported_names=("path",),
                ),
            ),
        )

    def scan_file(self, path: str) -> list[SymbolInfo]:
        return [
            SymbolInfo(
                name="main",
                kind=SymbolKind.FUNCTION,
                file_path=path,
                line=1,
                signature="def main() -> None",
            ),
        ]


class _InvalidRepoMapper:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestRepoMapperPortContract:
    """RepoMapperPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubRepoMapper()
        assert isinstance(impl, RepoMapperPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidRepoMapper()
        assert not isinstance(invalid, RepoMapperPort)

    def test_scan_repo_returns_repo_map(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_repo("/repo", {".py"})
        assert isinstance(result, RepoMap)

    def test_scan_repo_root_path_matches_input(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_repo("/my/repo", {".py"})
        assert result.root_path == "/my/repo"

    def test_scan_repo_files_are_tuple(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_repo("/repo", {".py"})
        assert isinstance(result.files, tuple)

    def test_scan_repo_symbols_are_tuple_of_symbol_info(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_repo("/repo", {".py"})
        assert isinstance(result.symbols, tuple)
        assert all(isinstance(s, SymbolInfo) for s in result.symbols)

    def test_scan_repo_imports_are_tuple_of_import_edge(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_repo("/repo", {".py"})
        assert isinstance(result.imports, tuple)
        assert all(isinstance(e, ImportEdge) for e in result.imports)

    def test_scan_file_returns_list_of_symbol_info(self) -> None:
        impl = _StubRepoMapper()
        result = impl.scan_file("main.py")
        assert isinstance(result, list)
        assert all(isinstance(s, SymbolInfo) for s in result)

    @pytest.mark.parametrize(
        "kind",
        [SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD],
    )
    def test_symbol_info_kind_is_symbol_kind(self, kind: SymbolKind) -> None:
        sym = SymbolInfo(name="x", kind=kind, file_path="f.py", line=1, signature="x")
        assert isinstance(sym.kind, SymbolKind)
