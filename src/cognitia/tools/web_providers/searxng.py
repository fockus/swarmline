"""SearXNG search provider — self-hosted метапоисковик.

Требует URL инстанса SearXNG (SEARXNG_URL).
Зависимость: httpx (уже в cognitia[web]).
"""

from __future__ import annotations

import httpx
import structlog

from cognitia.tools.web_protocols import SearchResult

_log = structlog.get_logger(component="web_search.searxng")


class SearXNGSearchProvider:
    """Поиск через SearXNG (self-hosted, без ограничений).

    Подключается к пользовательскому инстансу SearXNG по URL.
    """

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        if not base_url:
            raise ValueError("SEARXNG_URL обязателен для SearXNGSearchProvider")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск через SearXNG JSON API.

        Args:
            query: Поисковый запрос. Пустой/whitespace -> пустой список.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult. Пустой при ошибке подключения.
        """
        if not query or not query.strip():
            return []

        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/search",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            _log.warning("searxng_search_failed", query=query[:100], error=str(exc))
            return []

        results = data.get("results", [])[:max_results]
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in results
        ]
