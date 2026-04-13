"""Content extractors for rich file types (PDF, Jupyter notebooks).

All dependencies are lazy-imported to avoid hard requirements.
Sync I/O is wrapped in asyncio.to_thread to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


async def extract_pdf(source: str | bytes) -> str:
    """Extract text from a PDF file or raw PDF bytes using pymupdf4llm.

    Args:
        source: Absolute/relative path to a PDF file, or raw PDF bytes.

    Returns:
        Extracted text content.

    Raises:
        ImportError: pymupdf4llm is not installed.
    """
    try:
        import pymupdf4llm
    except ImportError:
        raise ImportError(
            "pymupdf4llm is required for PDF extraction. "
            "Install: pip install pymupdf4llm"
        ) from None

    if isinstance(source, bytes):
        try:
            import fitz
        except ImportError:
            raise ImportError(
                "pymupdf is required for PDF extraction from bytes. "
                "Install: pip install pymupdf"
            ) from None

        def _extract_from_bytes() -> str:
            doc = fitz.open(stream=source, filetype="pdf")
            try:
                return pymupdf4llm.to_markdown(doc)
            finally:
                doc.close()

        return await asyncio.to_thread(_extract_from_bytes)

    return await asyncio.to_thread(pymupdf4llm.to_markdown, source)


async def extract_jupyter(source: str | bytes) -> str:
    """Extract cell contents from a Jupyter notebook (.ipynb) or notebook JSON.

    Args:
        source: Absolute/relative path to the .ipynb file, notebook JSON string,
            or UTF-8 encoded notebook bytes.

    Returns:
        Extracted text (markdown + code cells concatenated).

    Raises:
        ImportError: nbformat is not installed.
    """
    try:
        import nbformat
    except ImportError:
        raise ImportError(
            "nbformat is required for Jupyter extraction. "
            "Install: pip install nbformat"
        ) from None

    if isinstance(source, bytes):
        notebook_text = source.decode("utf-8")
        nb = await asyncio.to_thread(nbformat.reads, notebook_text, as_version=4)
    elif Path(source).exists():
        nb = await asyncio.to_thread(nbformat.read, source, 4)
    else:
        nb = await asyncio.to_thread(nbformat.reads, source, as_version=4)

    parts: list[str] = []
    for cell in nb.cells:
        source = "".join(cell.source) if isinstance(cell.source, list) else cell.source
        if cell.cell_type == "markdown":
            parts.append(source)
        elif cell.cell_type == "code":
            parts.append(f"```python\n{source}\n```")
    return "\n\n".join(parts)
