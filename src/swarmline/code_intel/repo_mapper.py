"""ASTRepoMapper — Python AST-based repository scanner.

Implements RepoMapperPort. Walks directory tree, parses Python files via ast,
extracts symbols (classes, functions, methods) and import edges.
Handles SyntaxError gracefully (skips broken files).
"""

from __future__ import annotations

import ast
import logging
import os

from swarmline.code_intel.types import (
    ImportEdge,
    RepoMap,
    SymbolInfo,
    SymbolKind,
)

logger = logging.getLogger(__name__)

_EXCLUDED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".eggs",
    }
)


class ASTRepoMapper:
    """Python AST-based repository scanner implementing RepoMapperPort."""

    def scan_repo(self, root: str, extensions: set[str]) -> RepoMap:
        """Walk directory tree, parse files, build RepoMap."""
        root = os.path.realpath(root)
        files: list[str] = []
        all_symbols: list[SymbolInfo] = []
        all_imports: list[ImportEdge] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter excluded directories in-place to prevent descent
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

            for filename in filenames:
                if not any(filename.endswith(ext) for ext in extensions):
                    continue

                file_path = os.path.join(dirpath, filename)
                files.append(file_path)

                tree = self._parse_file(file_path)
                if tree is None:
                    continue

                symbols = self._extract_symbols(tree, file_path)
                all_symbols.extend(symbols)

                imports = self._extract_imports(tree, file_path)
                all_imports.extend(imports)

        return RepoMap(
            root_path=root,
            files=tuple(sorted(files)),
            symbols=tuple(all_symbols),
            imports=tuple(all_imports),
        )

    def scan_file(self, path: str) -> list[SymbolInfo]:
        """Parse a single file and return its symbols."""
        path = os.path.realpath(path)
        tree = self._parse_file(path)
        if tree is None:
            return []
        return self._extract_symbols(tree, path)

    def _parse_file(self, path: str) -> ast.Module | None:
        """Parse a Python file, returning None on SyntaxError."""
        try:
            with open(path, encoding="utf-8") as f:
                source = f.read()
            return ast.parse(source, filename=path)
        except SyntaxError:
            logger.warning("Skipping file with syntax error: %s", path)
            return None

    def _extract_symbols(self, tree: ast.Module, file_path: str) -> list[SymbolInfo]:
        """Extract symbol definitions from an AST."""
        symbols: list[SymbolInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind=SymbolKind.CLASS,
                        file_path=file_path,
                        line=node.lineno,
                        signature=f"class {node.name}",
                    )
                )
                # Extract methods
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            SymbolInfo(
                                name=item.name,
                                kind=SymbolKind.METHOD,
                                file_path=file_path,
                                line=item.lineno,
                                signature=self._function_signature(item),
                            )
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind=SymbolKind.FUNCTION,
                        file_path=file_path,
                        line=node.lineno,
                        signature=self._function_signature(node),
                    )
                )

        return symbols

    def _extract_imports(self, tree: ast.Module, file_path: str) -> list[ImportEdge]:
        """Extract import edges from an AST."""
        imports: list[ImportEdge] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportEdge(
                            source_file=file_path,
                            target_module=alias.name,
                            imported_names=(),
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = tuple(alias.name for alias in node.names)
                imports.append(
                    ImportEdge(
                        source_file=file_path,
                        target_module=module,
                        imported_names=names,
                    )
                )

        return imports

    def _function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Build a human-readable function signature from AST node."""
        args = node.args
        params: list[str] = []

        for arg in args.args:
            annotation = ""
            if arg.annotation:
                annotation = f": {ast.unparse(arg.annotation)}"
            params.append(f"{arg.arg}{annotation}")

        params_str = ", ".join(params)
        returns = ""
        if node.returns:
            returns = f" -> {ast.unparse(node.returns)}"

        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({params_str}){returns}"
