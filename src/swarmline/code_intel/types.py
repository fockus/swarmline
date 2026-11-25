"""Pure domain types for Code Intelligence — zero external dependencies.

Types for repository mapping, impact analysis, language seams, and edit planning.
Clean Architecture: no imports from runtime/, infrastructure/, or any SDK.

Types:
- SymbolKind: CLASS, FUNCTION, METHOD, VARIABLE, IMPORT
- SymbolInfo: frozen symbol definition with location and signature
- ImportEdge: directed import relationship between files
- RepoMap: complete repository snapshot (files, symbols, imports)
- ImpactResult: blast radius analysis for a set of target files
- LanguageSeam: public API point in a file (class, function, method)
- CoverageMapping: maps seam signatures to test files
- EditPlan: ordered edit plan with impact and coverage info
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class SymbolKind(enum.StrEnum):
    """Kind of code symbol extracted from source files."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """A single symbol definition in the repository."""

    name: str
    kind: SymbolKind
    file_path: str
    line: int
    signature: str


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """Directed import relationship: source_file imports from target_module."""

    source_file: str
    target_module: str
    imported_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepoMap:
    """Complete snapshot of repository structure: files, symbols, imports."""

    root_path: str
    files: tuple[str, ...]
    symbols: tuple[SymbolInfo, ...]
    imports: tuple[ImportEdge, ...]


@dataclass(frozen=True, slots=True)
class ImpactResult:
    """Blast radius analysis for a set of target files."""

    target_files: tuple[str, ...]
    directly_affected: tuple[str, ...]
    transitively_affected: tuple[str, ...]
    blast_radius_score: float


@dataclass(frozen=True, slots=True)
class LanguageSeam:
    """Public API point in a file — entry point for testing/refactoring."""

    file_path: str
    line: int
    kind: SymbolKind
    signature: str
    references_count: int


@dataclass(frozen=True, slots=True)
class CoverageMapping:
    """Maps seam signatures to tuples of test file paths that cover them."""

    seam_to_tests: dict[str, tuple[str, ...]]


def file_to_module(file_path: str, root_path: str) -> str:
    """Convert file path to Python-style module name.

    Shared utility — single source of truth for file→module conversion.

    Examples:
        file_to_module("utils.py", "/repo") -> "utils"
        file_to_module("pkg/utils.py", "/repo") -> "pkg.utils"
        file_to_module("/repo/pkg/utils.py", "/repo") -> "pkg.utils"
    """
    path = file_path
    if path.startswith(root_path):
        path = path[len(root_path) :].lstrip("/")
    if path.endswith(".py"):
        path = path[:-3]
    if path.endswith("/__init__"):
        path = path[: path.rfind("/__init__")]
    elif path == "__init__":
        path = ""
    return path.replace("/", ".")


@dataclass(frozen=True, slots=True)
class EditPlan:
    """Ordered edit plan with impact analysis and coverage info."""

    target_files: tuple[str, ...]
    ordered_edit_files: tuple[str, ...]
    impact: ImpactResult
    suggested_test_commands: tuple[str, ...]
    coverage: CoverageMapping | None
