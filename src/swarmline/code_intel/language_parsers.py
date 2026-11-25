"""Language parsers for finding public API seams in source files.

PythonSeamParser: AST-based parsing for Python files.
TypeScriptSeamParser: regex-based parsing for TypeScript files.
CompositeLanguageParser: extension-based routing to registered parsers.

All implement LanguageParserPort. Zero external dependencies (stdlib only).
"""

from __future__ import annotations

import ast
import os
import re

from swarmline.code_intel.protocols import LanguageParserPort
from swarmline.code_intel.types import LanguageSeam, SymbolKind


class PythonSeamParser:
    """Finds public API seams in Python files using the ast module.

    Extracts top-level functions, classes, and public methods.
    Skips names starting with underscore (private/dunder).
    """

    @property
    def supported_extensions(self) -> set[str]:
        return {".py"}

    def find_seams(self, file_path: str) -> list[LanguageSeam]:
        try:
            with open(file_path) as f:
                source = f.read()
        except (OSError, FileNotFoundError):
            return []

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        lines = source.splitlines()
        seams: list[LanguageSeam] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                seams.append(
                    _python_seam(file_path, node, SymbolKind.FUNCTION, lines, source)
                )
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("_"):
                    continue
                seams.append(
                    _python_seam(file_path, node, SymbolKind.CLASS, lines, source)
                )
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("_"):
                            continue
                        seams.append(
                            _python_seam(
                                file_path, item, SymbolKind.METHOD, lines, source
                            )
                        )

        return seams


def _python_seam(
    file_path: str,
    node: ast.AST,
    kind: SymbolKind,
    lines: list[str],
    source: str,
) -> LanguageSeam:
    """Build a LanguageSeam from an AST node."""
    lineno: int = getattr(node, "lineno", 1)
    name: str = getattr(node, "name", "")

    sig = lines[lineno - 1].strip() if lineno <= len(lines) else name
    if sig.endswith(":"):
        sig = sig[:-1].strip()

    return LanguageSeam(
        file_path=file_path,
        line=lineno,
        kind=kind,
        signature=sig,
        references_count=source.count(name),
    )


# ── TypeScript ──────────────────────────────────────────────────────────

_TS_FUNCTION_RE = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE
)
_TS_CLASS_RE = re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE)
_TS_INTERFACE_RE = re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE)
_TS_TYPE_ALIAS_RE = re.compile(r"^(?:export\s+)?type\s+(\w+)\s*=", re.MULTILINE)


class TypeScriptSeamParser:
    """Finds public API seams in TypeScript files using regex patterns.

    Detects function declarations, class declarations, interface declarations,
    and type aliases. No external dependencies required.
    """

    @property
    def supported_extensions(self) -> set[str]:
        return {".ts", ".tsx"}

    def find_seams(self, file_path: str) -> list[LanguageSeam]:
        try:
            with open(file_path) as f:
                source = f.read()
        except (OSError, FileNotFoundError):
            return []

        lines = source.splitlines()
        seams: list[LanguageSeam] = []

        for match in _TS_FUNCTION_RE.finditer(source):
            seams.append(_ts_seam(file_path, match, SymbolKind.FUNCTION, lines, source))

        for match in _TS_CLASS_RE.finditer(source):
            seams.append(_ts_seam(file_path, match, SymbolKind.CLASS, lines, source))

        for match in _TS_INTERFACE_RE.finditer(source):
            seams.append(_ts_seam(file_path, match, SymbolKind.CLASS, lines, source))

        for match in _TS_TYPE_ALIAS_RE.finditer(source):
            seams.append(_ts_seam(file_path, match, SymbolKind.VARIABLE, lines, source))

        seams.sort(key=lambda s: s.line)
        return seams


def _ts_seam(
    file_path: str,
    match: re.Match[str],
    kind: SymbolKind,
    lines: list[str],
    source: str,
) -> LanguageSeam:
    """Build a LanguageSeam from a regex match."""
    name = match.group(1)
    line_start = source[: match.start()].count("\n") + 1
    sig = lines[line_start - 1].strip() if line_start <= len(lines) else name
    if sig.endswith("{"):
        sig = sig[:-1].strip()

    return LanguageSeam(
        file_path=file_path,
        line=line_start,
        kind=kind,
        signature=sig,
        references_count=source.count(name),
    )


# ── Composite ───────────────────────────────────────────────────────────


class CompositeLanguageParser:
    """Routes find_seams calls to the appropriate language parser by file extension.

    Register parsers via register_parser(). Raises ValueError for unsupported extensions.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParserPort] = {}

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._parsers.keys())

    def register_parser(self, parser: LanguageParserPort) -> None:
        for ext in parser.supported_extensions:
            self._parsers[ext] = parser

    def find_seams(self, file_path: str) -> list[LanguageSeam]:
        ext = os.path.splitext(file_path)[1]
        parser = self._parsers.get(ext)
        if parser is None:
            raise ValueError(f"No parser registered for unsupported extension {ext!r}")
        return parser.find_seams(file_path)
