"""Brave Search provider — 2000 req/month бесплатно.

Требует API ключ (BRAVE_SEARCH_API_KEY).
Зависимость: httpx (уже в cognitia[web]).
API docs: https://api.search.brave.com/app/documentation/web-search
"""

from __future__ import annotations

import httpx
import structlog

from cognitia.tools.web_protocols import SearchResult

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_log = structlog.get_logger(component="web_search.brave")


class BraveSearchProvider:
    """Поиск через Brave Search API (free tier: 2000 req/month).

    Требует API key. Использует httpx для HTTP запросов.
    """

    def __init__(self, api_key: str, timeout: int = 15) -> None:
        if not api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY обязателен для BraveSearchProvider")
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск через Brave Search API.

        Args:
            query: Поисковый запрос. Пустой/whitespace -> пустой список.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult. Пустой при ошибке.
        """
        if not query or not query.strip():
            return []

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {
            "q": query,
            "count": max_results,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    _BRAVE_SEARCH_URL,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            _log.warning("brave_search_failed", query=query[:100], error=str(exc))
            return []

        web_results = data.get("web", {}).get("results", [])[:max_results]
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in web_results
        ]
