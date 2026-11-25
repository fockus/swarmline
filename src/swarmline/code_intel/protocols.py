"""Code Intelligence protocols — ISP-compliant ports for code analysis.

Each protocol has at most 5 methods. All are @runtime_checkable.
Imports only from code_intel.types (pure domain).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.code_intel.types import (
    CoverageMapping,
    ImpactResult,
    LanguageSeam,
    RepoMap,
    SymbolInfo,
)


@runtime_checkable
class RepoMapperPort(Protocol):
    """Port for scanning repository structure: files, symbols, imports."""

    def scan_repo(self, root: str, extensions: set[str]) -> RepoMap: ...
    def scan_file(self, path: str) -> list[SymbolInfo]: ...


@runtime_checkable
class ImpactAnalyzerPort(Protocol):
    """Port for analyzing blast radius of file changes."""

    def analyze_impact(
        self, repo_map: RepoMap, target_files: set[str]
    ) -> ImpactResult: ...


@runtime_checkable
class LanguageParserPort(Protocol):
    """Port for finding public API seams in source files."""

    def find_seams(self, file_path: str) -> list[LanguageSeam]: ...

    @property
    def supported_extensions(self) -> set[str]: ...


@runtime_checkable
class CoverageAnalyzerPort(Protocol):
    """Port for mapping seams to their covering test files."""

    def map_coverage(
        self, repo_map: RepoMap, seams: list[LanguageSeam]
    ) -> CoverageMapping: ...
