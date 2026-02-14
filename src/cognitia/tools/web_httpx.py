"""HttpxWebProvider — реализация WebProvider через httpx.

fetch: GET URL → trafilatura/regex → текст (работает всегда).
search: делегирует в pluggable WebSearchProvider (DIP).
Optional dependency: httpx, trafilatura.
"""

from __future__ import annotations

import re

import structlog

from cognitia.tools.web_protocols import SearchResult, WebFetchProvider, WebSearchProvider

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

_log = structlog.get_logger(component="web_httpx")


def _extract_text(html: str) -> str:
    """Извлечь текст из HTML: trafilatura → улучшенный regex fallback.

    Trafilatura (если установлен) извлекает основной контент страницы,
    отбрасывая навигацию, футеры, рекламу.
    Без trafilatura — regex удаляет script/style/теги.
    """
    if trafilatura is not None:
        text = trafilatura.extract(html, include_links=True) or ""
        if text:
            return text[:50000]

    # Улучшенный regex fallback: удаляем script, style, затем теги
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:50000]


class HttpxWebProvider:
    """WebProvider через httpx (async HTTP client).

    fetch: GET → trafilatura/regex → text. Или делегация в fetch_provider (Jina/Crawl4AI).
    search: делегирует в search_provider (DuckDuckGo, Tavily, SearXNG, Brave).
    """

    def __init__(
        self,
        timeout: int = 30,
        search_provider: WebSearchProvider | None = None,
        fetch_provider: WebFetchProvider | None = None,
    ) -> None:
        self._timeout = timeout
        self._search_provider = search_provider
        self._fetch_provider = fetch_provider

    async def fetch(self, url: str) -> str:
        """Загрузить URL, вернуть текстовое содержимое.

        Если задан fetch_provider (Jina/Crawl4AI) — делегирует.
        Иначе — httpx GET + trafilatura/regex.
        """
        if self._fetch_provider is not None:
            return await self._fetch_provider.fetch(url)

        try:
            import httpx
        except ImportError:
            return "httpx не установлен. pip install cognitia[web]"

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                return _extract_text(html)
        except Exception as exc:
            _log.warning("httpx_fetch_failed", url=url[:200], error=str(exc))
            return ""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск в интернете через pluggable provider.

        Делегирует в search_provider если он задан.
        Без провайдера возвращает пустой список.
        """
        if self._search_provider is None:
            return []
        return await self._search_provider.search(query, max_results)
