"""Jina Reader fetch provider - URL -> markdown via Jina AI Reader API.

Free tier: 1 million tokens. Requires JINA_API_KEY.
Dependency: httpx (already included in cognitia[web]).
API docs: https://jina.ai/reader
"""

from __future__ import annotations

import httpx
import structlog

_log = structlog.get_logger(component="web_fetch.jina")

_JINA_READER_BASE = "https://r.jina.ai/"


class JinaReaderFetchProvider:
    """Fetch a URL via the Jina Reader API -> clean markdown.

    Jina Reader converts HTML to LLM-friendly markdown,
    including tables, code, and LaTeX. Supports 29 languages.
    """

    def __init__(self, api_key: str, timeout: int = 30) -> None:
        if not api_key:
            raise ValueError("JINA_API_KEY обязателен для JinaReaderFetchProvider")
        self._api_key = api_key
        self._timeout = timeout

    async def fetch(self, url: str) -> str:
        """Extract page content via the Jina Reader API.

        Args:
            url: URL to load.

        Returns:
            Markdown content. Empty string on error.
        """
        if not url or not url.strip():
            return ""

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/markdown",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(
                    f"{_JINA_READER_BASE}{url.strip()}",
                    headers=headers,
                )
                response.raise_for_status()
                content = response.text
                return content[:50000]
        except (httpx.HTTPError, ValueError, OSError) as exc:
            _log.warning("jina_fetch_failed", url=url[:200], error=str(exc))
            return ""
