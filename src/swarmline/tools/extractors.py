"""Content extractors for rich file types (PDF, Jupyter notebooks).

All dependencies are lazy-imported to avoid hard requirements.
Sync I/O is wrapped in asyncio.to_thread to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio


async def extract_pdf(path: str) -> str:
    """Extract text from a PDF file using pymupdf4llm.

    Args:
        path: Absolute or relative path to the PDF file.

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

    return await asyncio.to_thread(pymupdf4llm.to_markdown, path)


async def extract_jupyter(path: str) -> str:
    """Extract cell contents from a Jupyter notebook (.ipynb).

    Args:
        path: Absolute or relative path to the .ipynb file.

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

    nb = await asyncio.to_thread(nbformat.read, path, 4)
    parts: list[str] = []
    for cell in nb.cells:
        source = "".join(cell.source) if isinstance(cell.source, list) else cell.source
        if cell.cell_type == "markdown":
            parts.append(source)
        elif cell.cell_type == "code":
            parts.append(f"```python\n{source}\n```")
    return "\n\n".join(parts)
