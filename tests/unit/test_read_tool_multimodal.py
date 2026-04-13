"""Tests for multimodal read tool — image detection, PDF/Jupyter extraction."""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from swarmline.tools.builtin import _create_read_executor
from swarmline.tools.protocols import BinaryReadProvider

_has_pymupdf4llm = False
try:
    import pymupdf4llm  # noqa: F401

    _has_pymupdf4llm = True
except ImportError:
    pass

_has_nbformat = False
try:
    import nbformat  # noqa: F401

    _has_nbformat = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# BinaryReadProvider protocol
# ---------------------------------------------------------------------------


class TestBinaryReadProviderProtocol:
    """BinaryReadProvider — separate ISP-compliant protocol for binary reads."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(BinaryReadProvider, "__protocol_attrs__") or hasattr(
            BinaryReadProvider, "__abstractmethods__"
        )

    def test_conforming_class_is_instance(self) -> None:
        class FakeBinary:
            async def read_file_bytes(self, path: str) -> bytes:
                return b""

        assert isinstance(FakeBinary(), BinaryReadProvider)

    def test_non_conforming_class_not_instance(self) -> None:
        class NotBinary:
            pass

        assert not isinstance(NotBinary(), BinaryReadProvider)


# ---------------------------------------------------------------------------
# Image detection in read executor
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
_TEXT_EXTENSIONS = [".py", ".txt", ".md", ".json", ".yaml"]


class _FakeSandboxWithBinary:
    """Fake sandbox that also supports binary reading."""

    def __init__(self, text_content: str = "", binary_content: bytes = b"") -> None:
        self._text = text_content
        self._binary = binary_content

    async def read_file(self, path: str) -> str:
        return self._text

    async def write_file(self, path: str, content: str) -> None:
        pass

    async def execute(self, command: str) -> None:
        pass

    async def list_dir(self, path: str = ".") -> list[str]:
        return []

    async def glob_files(self, pattern: str) -> list[str]:
        return []

    async def read_file_bytes(self, path: str) -> bytes:
        return self._binary


class _FakeSandboxTextOnly:
    """Fake sandbox without binary reading support."""

    def __init__(self, text_content: str = "") -> None:
        self._text = text_content

    async def read_file(self, path: str) -> str:
        return self._text

    async def write_file(self, path: str, content: str) -> None:
        pass

    async def execute(self, command: str) -> None:
        pass

    async def list_dir(self, path: str = ".") -> list[str]:
        return []

    async def glob_files(self, pattern: str) -> list[str]:
        return []


class TestReadExecutorImageDetection:
    """Read executor detects image files and returns base64."""

    @pytest.mark.parametrize("ext", _IMAGE_EXTENSIONS)
    async def test_image_file_returns_base64(self, ext: str) -> None:
        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        sandbox = _FakeSandboxWithBinary(binary_content=raw_bytes)
        executor = _create_read_executor(sandbox)
        result = json.loads(await executor({"path": f"photo{ext}"}))
        assert result["status"] == "ok"
        assert result["type"] == "image"
        assert result["data"] == base64.b64encode(raw_bytes).decode()
        assert "image/" in result["media_type"]

    @pytest.mark.parametrize("ext", _TEXT_EXTENSIONS)
    async def test_text_file_returns_content(self, ext: str) -> None:
        sandbox = _FakeSandboxWithBinary(text_content="hello world")
        executor = _create_read_executor(sandbox)
        result = json.loads(await executor({"path": f"file{ext}"}))
        assert result["status"] == "ok"
        assert result["content"] == "hello world"
        assert "type" not in result or result.get("type") != "image"

    async def test_image_without_binary_provider_falls_back_to_text(self) -> None:
        sandbox = _FakeSandboxTextOnly(text_content="binary-as-text-fallback")
        executor = _create_read_executor(sandbox)
        result = json.loads(await executor({"path": "photo.png"}))
        assert result["status"] == "ok"
        assert result["content"] == "binary-as-text-fallback"

    async def test_image_media_type_mapping(self) -> None:
        sandbox = _FakeSandboxWithBinary(binary_content=b"\xff\xd8\xff")
        executor = _create_read_executor(sandbox)

        result_png = json.loads(await executor({"path": "a.png"}))
        assert result_png["media_type"] == "image/png"

        result_jpg = json.loads(await executor({"path": "a.jpg"}))
        assert result_jpg["media_type"] == "image/jpeg"

        result_jpeg = json.loads(await executor({"path": "a.jpeg"}))
        assert result_jpeg["media_type"] == "image/jpeg"

        result_gif = json.loads(await executor({"path": "a.gif"}))
        assert result_gif["media_type"] == "image/gif"

        result_webp = json.loads(await executor({"path": "a.webp"}))
        assert result_webp["media_type"] == "image/webp"


# ---------------------------------------------------------------------------
# PDF extractor
# ---------------------------------------------------------------------------


class TestExtractPdf:
    """extract_pdf extracts text from PDF files via pymupdf4llm."""

    @pytest.mark.skipif(not _has_pymupdf4llm, reason="pymupdf4llm not installed")
    async def test_extract_pdf_returns_text(self, tmp_path: Path) -> None:
        from swarmline.tools.extractors import extract_pdf

        pdf_path = tmp_path / "test.pdf"
        _create_minimal_pdf(pdf_path)
        text = await extract_pdf(str(pdf_path))
        assert isinstance(text, str)

    async def test_extract_pdf_missing_dependency_raises(self) -> None:
        with patch.dict("sys.modules", {"pymupdf4llm": None}):
            from swarmline.tools import extractors

            # Force re-evaluation of the lazy import inside the function
            with pytest.raises(ImportError, match="pymupdf4llm"):
                await extractors.extract_pdf("/fake/path.pdf")


# ---------------------------------------------------------------------------
# Jupyter extractor
# ---------------------------------------------------------------------------


class TestExtractJupyter:
    """extract_jupyter extracts cell contents from .ipynb files."""

    @pytest.mark.skipif(not _has_nbformat, reason="nbformat not installed")
    async def test_extract_jupyter_returns_text(self, tmp_path: Path) -> None:
        from swarmline.tools.extractors import extract_jupyter

        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(
            json.dumps(
                {
                    "nbformat": 4,
                    "nbformat_minor": 2,
                    "metadata": {},
                    "cells": [
                        {"cell_type": "markdown", "source": ["# Title"], "metadata": {}},
                        {
                            "cell_type": "code",
                            "source": ["print('hello')"],
                            "metadata": {},
                            "outputs": [
                                {"output_type": "stream", "text": ["hello\n"], "name": "stdout"}
                            ],
                            "execution_count": 1,
                        },
                    ],
                }
            )
        )
        text = await extract_jupyter(str(nb_path))
        assert "Title" in text
        assert "print('hello')" in text

    async def test_extract_jupyter_missing_dependency_raises(self) -> None:
        with patch.dict("sys.modules", {"nbformat": None}):
            from swarmline.tools import extractors

            with pytest.raises(ImportError, match="nbformat"):
                await extractors.extract_jupyter("/fake/path.ipynb")


# ---------------------------------------------------------------------------
# Read executor integration with extractors
# ---------------------------------------------------------------------------


class TestReadExecutorExtractors:
    """Read executor integrates PDF/Jupyter extractors."""

    async def test_pdf_file_uses_extractor(self) -> None:
        sandbox = _FakeSandboxWithBinary()
        executor = _create_read_executor(sandbox)

        mock_extract = AsyncMock(return_value="Extracted PDF text")
        with patch("swarmline.tools.extractors.extract_pdf", mock_extract):
            result = json.loads(await executor({"path": "doc.pdf"}))
        assert result["status"] == "ok"
        assert result["content"] == "Extracted PDF text"
        mock_extract.assert_awaited_once_with("doc.pdf")

    async def test_ipynb_file_uses_extractor(self) -> None:
        sandbox = _FakeSandboxWithBinary()
        executor = _create_read_executor(sandbox)

        async def _mock_extract_jupyter(path: str) -> str:
            return "Notebook cells extracted"

        with patch("swarmline.tools.extractors.extract_jupyter", _mock_extract_jupyter):
            result = json.loads(await executor({"path": "notebook.ipynb"}))
        assert result["status"] == "ok"
        assert result["content"] == "Notebook cells extracted"

    async def test_pdf_extractor_error_returns_error_response(self) -> None:
        sandbox = _FakeSandboxWithBinary()
        executor = _create_read_executor(sandbox)

        async def _failing_extract(path: str) -> str:
            raise ImportError("pymupdf4llm is required")

        with patch("swarmline.tools.extractors.extract_pdf", _failing_extract):
            result = json.loads(await executor({"path": "doc.pdf"}))
        assert result["status"] == "error"
        assert "pymupdf4llm" in result["message"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_pdf(path: Path) -> None:
    """Create a minimal valid PDF for testing (requires pymupdf)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Test PDF content")
    doc.save(str(path))
    doc.close()
