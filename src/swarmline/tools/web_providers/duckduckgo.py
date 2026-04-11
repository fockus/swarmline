"""DuckDuckGo search provider - metasearch across 9 engines, no API keys.

Optional dependency: ddgs (pip install swarmline[web-duckduckgo]).
Engines: Bing, Google, Brave, DuckDuckGo, Yandex, Yahoo, Mojeek, Wikipedia, Grokipedia.
If the dependency is not installed, gracefully fall back to an empty list.
"""

from __future__ import annotations

import asyncio

import structlog

from swarmline.tools.web_protocols import SearchResult

try:
    from ddgs import DDGS  # type: ignore[import-not-found]
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]

_log = structlog.get_logger(component="web_search.duckduckgo")


class DuckDuckGoSearchProvider:
    """Metasearch via ddgs (9 engines, no API keys).

    Uses the ddgs library (formerly duckduckgo-search).
    Requests are executed synchronously via run_in_executor.
    """

    def __init__(self, timeout: int = 15) -> None:
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via ddgs.

        Args:
            query: Search query. Empty/whitespace -> empty list.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult. Empty if ddgs is unavailable or an error occurs.
        """
        if DDGS is None:
            return []
        if not query or not query.strip():
            return []

        def _sync_search() -> list[dict]:
            try:
                return list(DDGS().text(query, max_results=max_results, timeout=self._timeout))
            except Exception as exc:
                _log.warning("ddgs_search_failed", query=query[:100], error=str(exc))
                return []

        loop = asyncio.get_running_loop()
        raw_results = await loop.run_in_executor(None, _sync_search)

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            )
            for r in raw_results
        ]
