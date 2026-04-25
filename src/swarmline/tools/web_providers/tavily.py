"""Tavily search provider - AI-optimized search.

Requires an API key (TAVILY_API_KEY). Free tier: 1000 req/month.
Optional dependency: tavily-python (pip install swarmline[web-tavily]).
"""

from __future__ import annotations

import asyncio

import structlog

from swarmline.tools.web_protocols import SearchResult

try:
    from tavily import TavilyClient  # ty: ignore[unresolved-import]  # optional dep
except ImportError:
    TavilyClient = None  # type: ignore[assignment,misc]

_log = structlog.get_logger(component="web_search.tavily")


class TavilySearchProvider:
    """Search via the Tavily API (optimized for AI agents).

    Requires an API key. Falls back gracefully if tavily-python is missing.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TAVILY_API_KEY обязателен для TavilySearchProvider")
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via the Tavily API.

        Args:
            query: Search query. Empty/whitespace -> empty list.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult. Empty if tavily-python is unavailable or an error occurs.
        """
        if TavilyClient is None:
            return []
        if not query or not query.strip():
            return []

        def _sync_search() -> dict:
            try:
                client = TavilyClient(api_key=self._api_key)
                return client.search(query=query, max_results=max_results)
            except Exception as exc:
                _log.warning("tavily_search_failed", query=query[:100], error=str(exc))
                return {}

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _sync_search)

        results = response.get("results", [])
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in results
        ]
