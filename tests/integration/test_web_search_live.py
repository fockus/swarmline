"""Integration: live smoke tests for web search/fetch provayderov. Vypolnyayut real setevye queries. Propuskayutsya if zavisimost not ustanovlena.
Markery: @pytest.mark.integration, @pytest.mark.live.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

from swarmline.tools.web_httpx import HttpxWebProvider, _extract_text  # noqa: E402
from swarmline.tools.web_protocols import SearchResult  # noqa: E402

# Verify dostupnost ddgs
try:
    from ddgs import DDGS as _DDGS

    _HAS_DDGS = _DDGS is not None
except ImportError:
    _HAS_DDGS = False


@pytest.mark.integration
class TestDdgsLiveSearch:
    """Live poisk cherez ddgs (real setevoy query)."""

    @pytest.mark.skipif(not _HAS_DDGS, reason="ddgs не установлен")
    async def test_ddgs_returns_real_results(self) -> None:
        """ddgs returns >0 realnyh resultov on simple query."""
        from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        provider = DuckDuckGoSearchProvider(timeout=15)
        results = await provider.search("Python programming language", max_results=3)

        assert len(results) > 0, (
            "ddgs не вернул результатов — сеть недоступна или API изменился"
        )
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.title for r in results), "Заголовки не должны быть пустыми"
        assert all(r.url.startswith("http") for r in results), (
            "URL должны начинаться с http"
        )

    @pytest.mark.skipif(not _HAS_DDGS, reason="ddgs не установлен")
    async def test_ddgs_russian_query(self) -> None:
        """ddgs correctly obrabatyvaet russkoyazychnye queries."""
        from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        provider = DuckDuckGoSearchProvider(timeout=15)
        results = await provider.search("финансовая грамотность", max_results=3)

        assert len(results) > 0, "ddgs не вернул результатов на русский запрос"


@pytest.mark.integration
class TestDefaultFetchLive:
    """Live fetch cherez httpx (real setevoy query)."""

    async def test_fetch_returns_content(self) -> None:
        """httpx fetch returns notempty kontent."""
        web = HttpxWebProvider()
        content = await web.fetch("https://httpbin.org/html")

        assert len(content) > 100, "Контент слишком короткий"

    async def test_fetch_no_html_tags(self) -> None:
        """Result fetch not contains HTML tegov."""
        web = HttpxWebProvider()
        content = await web.fetch("https://httpbin.org/html")

        assert "<script" not in content.lower()
        assert "<style" not in content.lower()
        # Notkotorye <a> mogut ostatsya ot trafilatura include_links, no <div>/<p> - nott
        assert "<div" not in content.lower()


@pytest.mark.integration
class TestExtractTextQuality:
    """Kachestvo izvlecheniya teksta from HTML."""

    def test_real_html_script_removed(self) -> None:
        """JavaScript kod udalyaetsya from realnogo HTML."""
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
