"""Unit tests for ASTRepoMapper — TDD red phase first.

Tests cover: symbol extraction, import graph, syntax error handling,
directory filtering, empty repos, and contract compliance.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from swarmline.code_intel.protocols import RepoMapperPort
from swarmline.code_intel.repo_mapper import ASTRepoMapper
from swarmline.code_intel.types import SymbolKind


@pytest.fixture()
def mapper() -> ASTRepoMapper:
    return ASTRepoMapper()


@pytest.fixture()
def sample_repo(tmp_path: object) -> str:
    """Create a temp directory with sample Python files."""
    root = str(tmp_path)

    # main.py — functions, imports
    main_py = os.path.join(root, "main.py")
    with open(main_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            import os
            from pathlib import Path

            def main() -> None:
                pass

            async def async_helper(x: int) -> str:
                return str(x)
        """)
        )

    # models.py — class with methods
    models_py = os.path.join(root, "models.py")
    with open(models_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            from dataclasses import dataclass

            @dataclass
            class User:
                name: str

                def greet(self) -> str:
                    return f"Hello, {self.name}"

                async def save(self) -> None:
                    pass
        """)
        )

    # subdir/utils.py
    subdir = os.path.join(root, "subdir")
    os.makedirs(subdir)
    utils_py = os.path.join(subdir, "utils.py")
    with open(utils_py, "w") as f:
        f.write(
            textwrap.dedent("""\
            CONSTANT = 42

            def helper() -> int:
                return CONSTANT
        """)
        )

    return root


@pytest.fixture()
def repo_with_syntax_error(tmp_path: object) -> str:
    """Create a temp directory with one valid and one broken file."""
    root = str(tmp_path)

    good = os.path.join(root, "good.py")
    with open(good, "w") as f:
        f.write("def ok() -> None:\n    pass\n")

    bad = os.path.join(root, "bad.py")
    with open(bad, "w") as f:
        f.write("def broken(\n")

    return root


@pytest.fixture()
def repo_with_excluded_dirs(tmp_path: object) -> str:
    """Create a temp directory with excluded dirs (__pycache__, .git, .venv)."""
    root = str(tmp_path)

    # Valid file at root
    with open(os.path.join(root, "app.py"), "w") as f:
        f.write("def app() -> None:\n    pass\n")

    # Files in excluded dirs
    for dirname in ("__pycache__", ".git", ".venv", "node_modules"):
        d = os.path.join(root, dirname)
        os.makedirs(d)
        with open(os.path.join(d, "skip.py"), "w") as f:
            f.write("SKIP = True\n")

    return root


class TestASTRepoMapperContract:
    """ASTRepoMapper satisfies RepoMapperPort contract."""

    def test_isinstance_repo_mapper_port(self, mapper: ASTRepoMapper) -> None:
        assert isinstance(mapper, RepoMapperPort)


class TestScanRepo:
    """scan_repo tests."""

    def test_finds_all_python_files(
        self, mapper: ASTRepoMapper, sample_repo: str
    ) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        # main.py, models.py, subdir/utils.py
        assert len(result.files) == 3

    def test_root_path_matches(self, mapper: ASTRepoMapper, sample_repo: str) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        assert result.root_path == sample_repo

    def test_finds_classes(self, mapper: ASTRepoMapper, sample_repo: str) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        classes = [s for s in result.symbols if s.kind == SymbolKind.CLASS]
        assert len(classes) == 1
        assert classes[0].name == "User"

    def test_finds_functions(self, mapper: ASTRepoMapper, sample_repo: str) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        funcs = [s for s in result.symbols if s.kind == SymbolKind.FUNCTION]
        func_names = {f.name for f in funcs}
        assert {"main", "async_helper", "helper"} <= func_names

    def test_finds_methods(self, mapper: ASTRepoMapper, sample_repo: str) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        methods = [s for s in result.symbols if s.kind == SymbolKind.METHOD]
        method_names = {m.name for m in methods}
        assert {"greet", "save"} <= method_names

    def test_builds_import_edges(self, mapper: ASTRepoMapper, sample_repo: str) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        assert len(result.imports) > 0
        # main.py imports os and pathlib
        main_imports = [e for e in result.imports if e.source_file.endswith("main.py")]
        target_modules = {e.target_module for e in main_imports}
        assert "os" in target_modules
        assert "pathlib" in target_modules

    def test_import_from_has_imported_names(
        self, mapper: ASTRepoMapper, sample_repo: str
    ) -> None:
        result = mapper.scan_repo(sample_repo, {".py"})
        pathlib_imports = [e for e in result.imports if e.target_module == "pathlib"]
        assert len(pathlib_imports) == 1
        assert "Path" in pathlib_imports[0].imported_names

    def test_handles_syntax_error_gracefully(
        self, mapper: ASTRepoMapper, repo_with_syntax_error: str
    ) -> None:
        result = mapper.scan_repo(repo_with_syntax_error, {".py"})
        # Should still find the good file's symbols
        func_names = {s.name for s in result.symbols}
        assert "ok" in func_names
        # Both files discovered but broken one may have no symbols
        assert len(result.files) == 2

    def test_filters_excluded_directories(
        self, mapper: ASTRepoMapper, repo_with_excluded_dirs: str
    ) -> None:
        result = mapper.scan_repo(repo_with_excluded_dirs, {".py"})
        # Only app.py should be found, not files in excluded dirs
        assert len(result.files) == 1
        assert result.files[0].endswith("app.py")

    def test_empty_directory_returns_empty_repo_map(
        self, mapper: ASTRepoMapper, tmp_path: object
    ) -> None:
        result = mapper.scan_repo(str(tmp_path), {".py"})
        assert result.files == ()
        assert result.symbols == ()
        assert result.imports == ()


class TestScanFile:
    """scan_file tests."""

    def test_scan_file_extracts_symbols(
        self, mapper: ASTRepoMapper, sample_repo: str
    ) -> None:
        main_path = os.path.join(sample_repo, "main.py")
        symbols = mapper.scan_file(main_path)
        names = {s.name for s in symbols}
        assert "main" in names
        assert "async_helper" in names

    def test_scan_file_returns_correct_lines(
        self, mapper: ASTRepoMapper, sample_repo: str
    ) -> None:
        main_path = os.path.join(sample_repo, "main.py")
        symbols = mapper.scan_file(main_path)
        main_func = next(s for s in symbols if s.name == "main")
        assert main_func.line == 4

    def test_scan_file_syntax_error_returns_empty(
        self, mapper: ASTRepoMapper, repo_with_syntax_error: str
    ) -> None:
        bad_path = os.path.join(repo_with_syntax_error, "bad.py")
        symbols = mapper.scan_file(bad_path)
        assert symbols == []

    def test_scan_file_includes_signature(
        self, mapper: ASTRepoMapper, sample_repo: str
    ) -> None:
        models_path = os.path.join(sample_repo, "models.py")
        symbols = mapper.scan_file(models_path)
        user_class = next(s for s in symbols if s.name == "User")
        assert "User" in user_class.signature
