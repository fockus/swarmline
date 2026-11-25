"""Unit tests for language parsers: PythonSeamParser, TypeScriptSeamParser, CompositeLanguageParser."""

from __future__ import annotations

import pytest

from swarmline.code_intel.language_parsers import (
    CompositeLanguageParser,
    PythonSeamParser,
    TypeScriptSeamParser,
)
from swarmline.code_intel.protocols import LanguageParserPort
from swarmline.code_intel.types import SymbolKind


# ── PythonSeamParser ────────────────────────────────────────────────────


class TestPythonSeamParserFunctions:
    """Tests for Python function definition parsing."""

    def test_finds_function_def(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def hello(name: str) -> str:\n    return name\n")
        seams = PythonSeamParser().find_seams(str(f))

        assert len(seams) == 1
        assert seams[0].kind == SymbolKind.FUNCTION
        assert "hello" in seams[0].signature

    def test_finds_async_function_def(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("async def fetch(url: str) -> bytes:\n    return b''\n")
        seams = PythonSeamParser().find_seams(str(f))

        assert len(seams) == 1
        assert "fetch" in seams[0].signature

    def test_finds_multiple_functions(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        names = {s.signature for s in seams}
        assert any("foo" in n for n in names)
        assert any("bar" in n for n in names)


class TestPythonSeamParserClasses:
    """Tests for Python class definition parsing."""

    def test_finds_class_def(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class MyClass:\n    pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        classes = [s for s in seams if s.kind == SymbolKind.CLASS]
        assert len(classes) == 1
        assert "MyClass" in classes[0].signature

    def test_finds_class_with_bases(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Child(Parent):\n    pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        classes = [s for s in seams if s.kind == SymbolKind.CLASS]
        assert "Child" in classes[0].signature


class TestPythonSeamParserMethods:
    """Tests for Python method definition parsing."""

    def test_finds_method_as_method_kind(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Foo:\n    def bar(self) -> None:\n        pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        methods = [s for s in seams if s.kind == SymbolKind.METHOD]
        assert len(methods) == 1
        assert "bar" in methods[0].signature

    def test_skips_private_methods(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "class Foo:\n"
            "    def _private(self):\n        pass\n"
            "    def public(self):\n        pass\n"
        )
        seams = PythonSeamParser().find_seams(str(f))

        method_sigs = [s.signature for s in seams if s.kind == SymbolKind.METHOD]
        assert not any("_private" in sig for sig in method_sigs)
        assert any("public" in sig for sig in method_sigs)

    def test_skips_dunder_methods(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Foo:\n    def __repr__(self):\n        return 'Foo'\n")
        seams = PythonSeamParser().find_seams(str(f))

        methods = [s for s in seams if s.kind == SymbolKind.METHOD]
        assert len(methods) == 0


class TestPythonSeamParserEdgeCases:
    """Tests for edge cases and metadata."""

    def test_supported_extensions(self) -> None:
        assert PythonSeamParser().supported_extensions == {".py"}

    def test_malformed_file_returns_empty(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        seams = PythonSeamParser().find_seams(str(f))

        assert seams == []

    def test_empty_file_returns_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        seams = PythonSeamParser().find_seams(str(f))

        assert seams == []

    def test_line_numbers_correct(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("# comment\n\ndef foo():\n    pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        foo = [s for s in seams if "foo" in s.signature][0]
        assert foo.line == 3

    def test_file_path_set_correctly(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def foo():\n    pass\n")
        seams = PythonSeamParser().find_seams(str(f))

        assert seams[0].file_path == str(f)

    def test_references_count_reflects_usage(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def foo():\n    pass\n\nresult = foo()\nfoo()\n")
        seams = PythonSeamParser().find_seams(str(f))

        foo = [s for s in seams if "foo" in s.signature][0]
        assert foo.references_count >= 2  # at least definition + calls

    def test_satisfies_language_parser_port(self) -> None:
        assert isinstance(PythonSeamParser(), LanguageParserPort)

    def test_nonexistent_file_returns_empty(self) -> None:
        seams = PythonSeamParser().find_seams("/nonexistent/path.py")
        assert seams == []


# ── TypeScriptSeamParser ────────────────────────────────────────────────


class TestTypeScriptSeamParserFunctions:
    """Tests for TypeScript function/class/interface parsing."""

    def test_finds_function_declaration(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("function greet(name: string): string {\n  return name;\n}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert len(seams) >= 1
        assert any(
            s.kind == SymbolKind.FUNCTION and "greet" in s.signature for s in seams
        )

    def test_finds_export_function(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("export function getData(): void {}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any("getData" in s.signature for s in seams)

    def test_finds_async_function(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("async function fetchData(): Promise<void> {}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any("fetchData" in s.signature for s in seams)


class TestTypeScriptSeamParserClasses:
    """Tests for TypeScript class parsing."""

    def test_finds_class_declaration(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("class UserService {\n  getData() {}\n}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any(
            s.kind == SymbolKind.CLASS and "UserService" in s.signature for s in seams
        )

    def test_finds_export_class(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("export class AppConfig {}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any("AppConfig" in s.signature for s in seams)


class TestTypeScriptSeamParserInterfaces:
    """Tests for TypeScript interface and type alias parsing."""

    def test_finds_interface_declaration(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("interface UserProps {\n  name: string;\n}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any(
            s.kind == SymbolKind.CLASS and "UserProps" in s.signature for s in seams
        )

    def test_finds_type_alias(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("type UserId = string;\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any("UserId" in s.signature for s in seams)

    def test_finds_export_interface(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("export interface Config {\n  port: number;\n}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert any("Config" in s.signature for s in seams)


class TestTypeScriptSeamParserEdgeCases:
    """Tests for edge cases."""

    def test_supported_extensions(self) -> None:
        assert TypeScriptSeamParser().supported_extensions == {".ts", ".tsx"}

    def test_empty_file_returns_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "empty.ts"
        f.write_text("")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert seams == []

    def test_satisfies_language_parser_port(self) -> None:
        assert isinstance(TypeScriptSeamParser(), LanguageParserPort)

    def test_nonexistent_file_returns_empty(self) -> None:
        seams = TypeScriptSeamParser().find_seams("/nonexistent/path.ts")
        assert seams == []

    def test_file_path_set_correctly(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("function foo(): void {}\n")
        seams = TypeScriptSeamParser().find_seams(str(f))

        assert seams[0].file_path == str(f)


# ── CompositeLanguageParser ─────────────────────────────────────────────


class TestCompositeLanguageParser:
    """Tests for composite parser routing."""

    def test_routes_py_to_python_parser(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def hello():\n    pass\n")
        composite = CompositeLanguageParser()
        composite.register_parser(PythonSeamParser())
        seams = composite.find_seams(str(f))

        assert any("hello" in s.signature for s in seams)

    def test_routes_ts_to_typescript_parser(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "mod.ts"
        f.write_text("function hello(): void {}\n")
        composite = CompositeLanguageParser()
        composite.register_parser(TypeScriptSeamParser())
        seams = composite.find_seams(str(f))

        assert any("hello" in s.signature for s in seams)

    def test_unsupported_extension_raises_value_error(self) -> None:
        composite = CompositeLanguageParser()
        with pytest.raises(ValueError, match="unsupported"):
            composite.find_seams("file.rb")

    def test_supported_extensions_union_of_registered(self) -> None:
        composite = CompositeLanguageParser()
        composite.register_parser(PythonSeamParser())
        composite.register_parser(TypeScriptSeamParser())

        assert composite.supported_extensions == {".py", ".ts", ".tsx"}

    def test_register_parser_adds_extensions(self) -> None:
        composite = CompositeLanguageParser()
        assert composite.supported_extensions == set()

        composite.register_parser(PythonSeamParser())
        assert ".py" in composite.supported_extensions

    def test_satisfies_language_parser_port(self) -> None:
        assert isinstance(CompositeLanguageParser(), LanguageParserPort)
