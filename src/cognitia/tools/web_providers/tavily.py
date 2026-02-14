"""Tavily search provider — AI-оптимизированный поиск.

Требует API ключ (TAVILY_API_KEY). Free tier: 1000 req/month.
Optional dependency: tavily-python (pip install cognitia[web-tavily]).
"""

from __future__ import annotations

import asyncio

import structlog

from cognitia.tools.web_protocols import SearchResult

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None  # type: ignore[assignment,misc]

_log = structlog.get_logger(component="web_search.tavily")


class TavilySearchProvider:
    """Поиск через Tavily API (оптимизирован для AI-агентов).

    Требует API key. При отсутствии tavily-python — graceful fallback.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TAVILY_API_KEY обязателен для TavilySearchProvider")
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск через Tavily API.

        Args:
            query: Поисковый запрос. Пустой/whitespace -> пустой список.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult. Пустой при отсутствии tavily-python или ошибке.
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
