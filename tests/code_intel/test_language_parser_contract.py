"""Contract tests for LanguageParserPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing find_seams + supported_extensions should pass.
"""

from __future__ import annotations

from swarmline.code_intel.protocols import LanguageParserPort
from swarmline.code_intel.types import LanguageSeam, SymbolKind


class _StubLanguageParser:
    """Minimal valid implementation for contract testing."""

    @property
    def supported_extensions(self) -> set[str]:
        return {".py"}

    def find_seams(self, file_path: str) -> list[LanguageSeam]:
        return [
            LanguageSeam(
                file_path=file_path,
                line=1,
                kind=SymbolKind.FUNCTION,
                signature="def main() -> None",
                references_count=3,
            ),
        ]


class _InvalidLanguageParser:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestLanguageParserPortContract:
    """LanguageParserPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubLanguageParser()
        assert isinstance(impl, LanguageParserPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidLanguageParser()
        assert not isinstance(invalid, LanguageParserPort)

    def test_find_seams_returns_list_of_language_seam(self) -> None:
        impl = _StubLanguageParser()
        result = impl.find_seams("main.py")
        assert isinstance(result, list)
        assert all(isinstance(s, LanguageSeam) for s in result)

    def test_find_seams_seam_has_required_fields(self) -> None:
        impl = _StubLanguageParser()
        seams = impl.find_seams("main.py")
        seam = seams[0]
        assert seam.file_path == "main.py"
        assert isinstance(seam.line, int)
        assert isinstance(seam.kind, SymbolKind)
        assert isinstance(seam.signature, str)
        assert isinstance(seam.references_count, int)

    def test_supported_extensions_returns_set_of_str(self) -> None:
        impl = _StubLanguageParser()
        exts = impl.supported_extensions
        assert isinstance(exts, set)
        assert all(isinstance(e, str) for e in exts)
        assert len(exts) > 0

    def test_supported_extensions_contain_dot_prefix(self) -> None:
        impl = _StubLanguageParser()
        exts = impl.supported_extensions
        assert all(e.startswith(".") for e in exts)
