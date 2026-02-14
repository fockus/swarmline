"""Integration: live smoke тесты для web search/fetch провайдеров.

Выполняют реальные сетевые запросы. Пропускаются если зависимость не установлена.
Маркер: @pytest.mark.integration.
"""

from __future__ import annotations

import pytest

from cognitia.tools.web_httpx import HttpxWebProvider, _extract_text
from cognitia.tools.web_protocols import SearchResult

# Проверяем доступность ddgs
try:
    from ddgs import DDGS as _DDGS

    _HAS_DDGS = _DDGS is not None
except ImportError:
    _HAS_DDGS = False


@pytest.mark.integration
class TestDdgsLiveSearch:
    """Live поиск через ddgs (реальный сетевой запрос)."""

    @pytest.mark.skipif(not _HAS_DDGS, reason="ddgs не установлен")
    async def test_ddgs_returns_real_results(self) -> None:
        """ddgs возвращает >0 реальных результатов на простой запрос."""
        from cognitia.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        provider = DuckDuckGoSearchProvider(timeout=15)
        results = await provider.search("Python programming language", max_results=3)

        assert len(results) > 0, "ddgs не вернул результатов — сеть недоступна или API изменился"
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.title for r in results), "Заголовки не должны быть пустыми"
        assert all(r.url.startswith("http") for r in results), "URL должны начинаться с http"

    @pytest.mark.skipif(not _HAS_DDGS, reason="ddgs не установлен")
    async def test_ddgs_russian_query(self) -> None:
        """ddgs корректно обрабатывает русскоязычные запросы."""
        from cognitia.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        provider = DuckDuckGoSearchProvider(timeout=15)
        results = await provider.search("финансовая грамотность", max_results=3)

        assert len(results) > 0, "ddgs не вернул результатов на русский запрос"


@pytest.mark.integration
class TestDefaultFetchLive:
    """Live fetch через httpx (реальный сетевой запрос)."""

    async def test_fetch_returns_content(self) -> None:
        """httpx fetch возвращает непустой контент."""
        web = HttpxWebProvider()
        content = await web.fetch("https://httpbin.org/html")

        assert len(content) > 100, "Контент слишком короткий"

    async def test_fetch_no_html_tags(self) -> None:
        """Результат fetch не содержит HTML тегов."""
        web = HttpxWebProvider()
        content = await web.fetch("https://httpbin.org/html")

        assert "<script" not in content.lower()
        assert "<style" not in content.lower()
        # Некоторые <a> могут остаться от trafilatura include_links, но <div>/<p> — нет
        assert "<div" not in content.lower()


@pytest.mark.integration
class TestExtractTextQuality:
    """Качество извлечения текста из HTML."""

    def test_real_html_script_removed(self) -> None:
        """JavaScript код удаляется из реального HTML."""
        html = """
        <html>
        <head><script>
            var analytics = {track: function() {}};
            analytics.track('pageview');
        </script></head>
        <body>
            <nav><a href="/">Home</a></nav>
            <main><h1>Article</h1><p>Important content here.</p></main>
            <footer>Copyright 2025</footer>
            <script>console.log('loaded');</script>
        </body>
        </html>
        """
        text = _extract_text(html)

        assert "Important content" in text
        assert "analytics" not in text
        assert "console.log" not in text
        assert "var " not in text
