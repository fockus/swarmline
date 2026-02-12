"""HttpxWebProvider — базовая реализация WebProvider через httpx.

MVP: fetch URL → текст, search → заглушка.
Optional dependency: httpx.
"""

from __future__ import annotations

import re

from cognitia.tools.web_protocols import SearchResult


class HttpxWebProvider:
    """WebProvider через httpx (async HTTP client).

    fetch: GET → strip HTML tags → text.
    search: MVP заглушка (возвращает пустой список).
    """

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def fetch(self, url: str) -> str:
        """Загрузить URL, вернуть текстовое содержимое."""
        try:
            import httpx
        except ImportError:
            return "httpx не установлен. pip install cognitia[web]"

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
            # Простое извлечение текста: убираем HTML-теги
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:50000]  # Ограничиваем размер

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск — MVP заглушка. Расширяется через DuckDuckGo/SearXNG."""
        return []
