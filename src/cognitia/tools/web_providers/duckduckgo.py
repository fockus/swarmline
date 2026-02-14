"""DuckDuckGo search provider — метапоиск по 9 движкам, без API ключей.

Optional dependency: ddgs (pip install cognitia[web-duckduckgo]).
Движки: Bing, Google, Brave, DuckDuckGo, Yandex, Yahoo, Mojeek, Wikipedia, Grokipedia.
Если зависимость не установлена — graceful fallback на пустой список.
"""

from __future__ import annotations

import asyncio

import structlog

from cognitia.tools.web_protocols import SearchResult

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]

_log = structlog.get_logger(component="web_search.duckduckgo")


class DuckDuckGoSearchProvider:
    """Метапоиск через ddgs (9 движков, без API ключей).

    Используется библиотека ddgs (бывший duckduckgo-search).
    Запросы выполняются синхронно через run_in_executor.
    """

    def __init__(self, timeout: int = 15) -> None:
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск через ddgs.

        Args:
            query: Поисковый запрос. Пустой/whitespace -> пустой список.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult. Пустой при отсутствии ddgs или ошибке.
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
