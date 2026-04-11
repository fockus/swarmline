"""Tests pluggable web search providers. Pokryvaet:
- WebSearchProvider Protocol compliance
- Kazhdyy provayder: search, edge cases, fallback
- Factory: createdie by imeni, unknown -> None
- HttpxWebProvider: delegatsiya search -> provider
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from swarmline.tools.web_httpx import HttpxWebProvider
from swarmline.tools.web_protocols import SearchResult, WebFetchProvider, WebSearchProvider
from swarmline.tools.web_providers.brave import BraveSearchProvider
from swarmline.tools.web_providers.crawl4ai import Crawl4AIFetchProvider
from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider
from swarmline.tools.web_providers.factory import (
    SUPPORTED_FETCH_PROVIDERS,
    SUPPORTED_PROVIDERS,
    create_fetch_provider,
    create_search_provider,
)
from swarmline.tools.web_providers.jina import JinaReaderFetchProvider
from swarmline.tools.web_providers.searxng import SearXNGSearchProvider
from swarmline.tools.web_providers.tavily import TavilySearchProvider

# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Vse provaydery realizuyut WebSearchProvider Protocol."""

    def test_duckduckgo_is_web_search_provider(self) -> None:
        provider = DuckDuckGoSearchProvider()
        assert isinstance(provider, WebSearchProvider)

    def test_tavily_is_web_search_provider(self) -> None:
        provider = TavilySearchProvider(api_key="test-key")
        assert isinstance(provider, WebSearchProvider)

    def test_searxng_is_web_search_provider(self) -> None:
        provider = SearXNGSearchProvider(base_url="http://localhost:8080")
        assert isinstance(provider, WebSearchProvider)

    def test_brave_is_web_search_provider(self) -> None:
        provider = BraveSearchProvider(api_key="test-key")
        assert isinstance(provider, WebSearchProvider)


# ---------------------------------------------------------------------------
# DuckDuckGo
# ---------------------------------------------------------------------------


class TestDuckDuckGoSearchProvider:
    """DuckDuckGoSearchProvider - metapoisk cherez ddgs (9 dvizhkov, without API key)."""

    async def test_search_returns_results(self) -> None:
        """S ustanovlennym ddgs returns SearchResult."""
        import swarmline.tools.web_providers.duckduckgo as ddg_mod

        mock_results = [
            {"title": "Python", "href": "https://python.org", "body": "Official site"},
            {"title": "PyPI", "href": "https://pypi.org", "body": "Package index"},
        ]

        # ddgs API: DDGS().text(query, max_results=N, timeout=T) - without context manager
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=mock_results)
        mock_ddgs_cls = MagicMock(return_value=mock_ddgs_instance)

        original = ddg_mod.DDGS
        ddg_mod.DDGS = mock_ddgs_cls
        try:
            provider = DuckDuckGoSearchProvider()
            results = await provider.search("python", max_results=2)
        finally:
            ddg_mod.DDGS = original

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].title == "Python"
        assert results[0].url == "https://python.org"
        assert results[0].snippet == "Official site"

    async def test_search_respects_max_results(self) -> None:
        """max_results and timeout are passed in DDGS().text()."""
        import swarmline.tools.web_providers.duckduckgo as ddg_mod

        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=[])
        mock_ddgs_cls = MagicMock(return_value=mock_ddgs_instance)

        original = ddg_mod.DDGS
        ddg_mod.DDGS = mock_ddgs_cls
        try:
            provider = DuckDuckGoSearchProvider(timeout=20)
            await provider.search("test", max_results=3)
        finally:
            ddg_mod.DDGS = original

        mock_ddgs_instance.text.assert_called_once_with("test", max_results=3, timeout=20)

    async def test_missing_dep_returns_empty(self) -> None:
        """Without ddgs (not ustanovlen) -> empty list (graceful)."""
        import swarmline.tools.web_providers.duckduckgo as ddg_mod

        original = ddg_mod.DDGS
        ddg_mod.DDGS = None
        try:
            provider = DuckDuckGoSearchProvider()
            results = await provider.search("test")
        finally:
            ddg_mod.DDGS = original

        assert results == []

    async def test_empty_query_returns_empty(self) -> None:
        """Empty query -> empty list without vyzova DDGS."""
        provider = DuckDuckGoSearchProvider()
        assert await provider.search("") == []
        assert await provider.search("   ") == []

    async def test_exception_returns_empty_and_logs(self) -> None:
        """Timeout/network error -> empty list + structlog warning."""
        import swarmline.tools.web_providers.duckduckgo as ddg_mod

        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(side_effect=RuntimeError("Timeout"))
        mock_ddgs_cls = MagicMock(return_value=mock_ddgs_instance)

        original = ddg_mod.DDGS
        ddg_mod.DDGS = mock_ddgs_cls
        try:
            provider = DuckDuckGoSearchProvider()
            results = await provider.search("test query")
        finally:
            ddg_mod.DDGS = original

        assert results == []


# ---------------------------------------------------------------------------
# Tavily
# ---------------------------------------------------------------------------


class TestTavilySearchProvider:
    """TavilySearchProvider - AI-optimizirovannyy, trebuet API key."""

    def test_missing_key_raises(self) -> None:
        """Without API key -> ValueError."""
        with pytest.raises(ValueError, match="TAVILY_API_KEY"):
            TavilySearchProvider(api_key="")

    async def test_empty_query_returns_empty(self) -> None:
        """Empty query -> empty list."""
        provider = TavilySearchProvider(api_key="test-key")
        assert await provider.search("") == []
        assert await provider.search("   ") == []

    async def test_exception_returns_empty(self) -> None:
        """API error -> empty list (graceful)."""
        import swarmline.tools.web_providers.tavily as tavily_mod

        mock_client = MagicMock()
        mock_client.search = MagicMock(side_effect=RuntimeError("API error"))
        mock_tavily_cls = MagicMock(return_value=mock_client)

        original = tavily_mod.TavilyClient
        tavily_mod.TavilyClient = mock_tavily_cls
        try:
            provider = TavilySearchProvider(api_key="test-key")
            results = await provider.search("test")
        finally:
            tavily_mod.TavilyClient = original

        assert results == []

    async def test_search_returns_results(self) -> None:
        """S ustanovlennym tavily-python returns SearchResult."""
        import swarmline.tools.web_providers.tavily as tavily_mod

        mock_response = {
            "results": [
                {"title": "Tavily", "url": "https://tavily.com", "content": "AI search"},
            ]
        }

        mock_client = MagicMock()
        mock_client.search = MagicMock(return_value=mock_response)
        mock_tavily_cls = MagicMock(return_value=mock_client)

        original = tavily_mod.TavilyClient
        tavily_mod.TavilyClient = mock_tavily_cls
        try:
            provider = TavilySearchProvider(api_key="test-key")
            results = await provider.search("AI search", max_results=1)
        finally:
            tavily_mod.TavilyClient = original

        assert len(results) == 1
        assert results[0].title == "Tavily"
        assert results[0].url == "https://tavily.com"

    async def test_missing_dep_returns_empty(self) -> None:
        """Without TavilyClient -> empty list."""
        import swarmline.tools.web_providers.tavily as tavily_mod

        original = tavily_mod.TavilyClient
        tavily_mod.TavilyClient = None
        try:
            provider = TavilySearchProvider(api_key="test-key")
            results = await provider.search("test")
        finally:
            tavily_mod.TavilyClient = original

        assert results == []


# ---------------------------------------------------------------------------
# SearXNG
# ---------------------------------------------------------------------------


class TestSearXNGSearchProvider:
    """SearXNGSearchProvider - self-hosted metapoiskovik."""

    def test_missing_url_raises(self) -> None:
        """Without URL -> ValueError."""
        with pytest.raises(ValueError, match="SEARXNG_URL"):
            SearXNGSearchProvider(base_url="")

    async def test_empty_query_returns_empty(self) -> None:
        """Empty query -> empty list."""
        provider = SearXNGSearchProvider(base_url="http://localhost:8080")
        assert await provider.search("") == []
        assert await provider.search("   ") == []

    async def test_search_returns_results(self) -> None:
        """HTTP JSON response → SearchResult."""
        mock_json = {
            "results": [
                {"title": "SearXNG", "url": "https://searxng.org", "content": "Metasearch"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value=mock_json)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as real_httpx

        with patch("swarmline.tools.web_providers.searxng.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            mock_httpx.HTTPError = real_httpx.HTTPError

            provider = SearXNGSearchProvider(base_url="http://localhost:8080")
            results = await provider.search("test", max_results=1)

        assert len(results) == 1
        assert results[0].title == "SearXNG"

    async def test_connection_error_returns_empty(self) -> None:
        """Error podklyucheniya -> empty list."""
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=real_httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("swarmline.tools.web_providers.searxng.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            mock_httpx.HTTPError = real_httpx.HTTPError

            provider = SearXNGSearchProvider(base_url="http://localhost:8080")
            results = await provider.search("test")

        assert results == []


# ---------------------------------------------------------------------------
# Brave Search
# ---------------------------------------------------------------------------


class TestBraveSearchProvider:
    """BraveSearchProvider - 2000 req/month besplatno."""

    def test_missing_key_raises(self) -> None:
        """Without API key -> ValueError."""
        with pytest.raises(ValueError, match="BRAVE_SEARCH_API_KEY"):
            BraveSearchProvider(api_key="")

    async def test_empty_query_returns_empty(self) -> None:
        """Empty query -> empty list."""
        provider = BraveSearchProvider(api_key="test-key")
        assert await provider.search("") == []
        assert await provider.search("   ") == []

    async def test_search_returns_results(self) -> None:
        """HTTP JSON response → SearchResult."""
        mock_json = {
            "web": {
                "results": [
                    {"title": "Brave", "url": "https://brave.com", "description": "Browser"},
                ]
            }
        }

        mock_response = AsyncMock()
        mock_response.json = MagicMock(return_value=mock_json)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as real_httpx

        with patch("swarmline.tools.web_providers.brave.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            mock_httpx.HTTPError = real_httpx.HTTPError

            provider = BraveSearchProvider(api_key="test-key")
            results = await provider.search("test", max_results=1)

        assert len(results) == 1
        assert results[0].title == "Brave"
        assert results[0].snippet == "Browser"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestSearchFactory:
    """create_search_provider() - factory by imeni (OCP)."""

    def test_creates_duckduckgo(self) -> None:
        provider = create_search_provider("duckduckgo")
        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_creates_tavily_with_key(self) -> None:
        provider = create_search_provider("tavily", api_key="test-key")
        assert isinstance(provider, TavilySearchProvider)

    def test_creates_searxng_with_url(self) -> None:
        provider = create_search_provider("searxng", base_url="http://localhost:8080")
        assert isinstance(provider, SearXNGSearchProvider)

    def test_creates_brave_with_key(self) -> None:
        provider = create_search_provider("brave", api_key="test-key")
        assert isinstance(provider, BraveSearchProvider)

    def test_unknown_provider_returns_none(self) -> None:
        provider = create_search_provider("unknown")
        assert provider is None

    def test_supported_providers_set(self) -> None:
        assert {"duckduckgo", "tavily", "searxng", "brave"} == SUPPORTED_PROVIDERS


# ---------------------------------------------------------------------------
# Jina Reader fetch provider
# ---------------------------------------------------------------------------


class TestJinaReaderFetchProvider:
    """JinaReaderFetchProvider - URL -> markdown cherez Jina AI."""

    def test_missing_key_raises(self) -> None:
        """Without API key -> ValueError."""
        with pytest.raises(ValueError, match="JINA_API_KEY"):
            JinaReaderFetchProvider(api_key="")

    def test_is_web_fetch_provider(self) -> None:
        """Realizuet WebFetchProvider Protocol."""
        provider = JinaReaderFetchProvider(api_key="test-key")
        assert isinstance(provider, WebFetchProvider)

    async def test_returns_markdown(self) -> None:
        """HTTP 200 -> markdown kontent."""
        mock_response = AsyncMock()
        mock_response.text = "# Title\n\nSome content here"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("swarmline.tools.web_providers.jina.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            import httpx as real_httpx

            mock_httpx.HTTPError = real_httpx.HTTPError

            provider = JinaReaderFetchProvider(api_key="test-key")
            result = await provider.fetch("https://example.com")

        assert result == "# Title\n\nSome content here"
        # Verify chto URL built pravilno
        call_args = mock_client.get.call_args
        assert "r.jina.ai/https://example.com" in call_args[0][0]

    async def test_network_error_returns_empty(self) -> None:
        """Error seti -> empty string."""
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=real_httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("swarmline.tools.web_providers.jina.httpx") as mock_httpx:
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
            mock_httpx.HTTPError = real_httpx.HTTPError

            provider = JinaReaderFetchProvider(api_key="test-key")
            result = await provider.fetch("https://example.com")

        assert result == ""

    async def test_empty_url_returns_empty(self) -> None:
        """Empty URL -> empty string."""
        provider = JinaReaderFetchProvider(api_key="test-key")
        assert await provider.fetch("") == ""
        assert await provider.fetch("   ") == ""


# ---------------------------------------------------------------------------
# Crawl4AI fetch provider
# ---------------------------------------------------------------------------


class TestCrawl4AIFetchProvider:
    """Crawl4AIFetchProvider - URL -> markdown cherez Crawl4AI."""

    def test_is_web_fetch_provider(self) -> None:
        """Realizuet WebFetchProvider Protocol."""
        provider = Crawl4AIFetchProvider()
        assert isinstance(provider, WebFetchProvider)

    async def test_missing_dep_returns_empty(self) -> None:
        """Without crawl4ai (not ustanovlen) -> empty string."""
        import swarmline.tools.web_providers.crawl4ai as crawl_mod

        original = crawl_mod.AsyncWebCrawler
        crawl_mod.AsyncWebCrawler = None
        try:
            provider = Crawl4AIFetchProvider()
            result = await provider.fetch("https://example.com")
        finally:
            crawl_mod.AsyncWebCrawler = original

        assert result == ""

    async def test_empty_url_returns_empty(self) -> None:
        """Empty URL -> empty string."""
        provider = Crawl4AIFetchProvider()
        # Dazhe pri ustanovlennom crawl4ai, empty URL -> ""
        import swarmline.tools.web_providers.crawl4ai as crawl_mod

        original = crawl_mod.AsyncWebCrawler
        crawl_mod.AsyncWebCrawler = None
        try:
            assert await provider.fetch("") == ""
        finally:
            crawl_mod.AsyncWebCrawler = original


# ---------------------------------------------------------------------------
# Fetch factory
# ---------------------------------------------------------------------------


class TestFetchFactory:
    """create_fetch_provider() - factory for fetch provayderov."""

    def test_default_returns_none(self) -> None:
        """'default' -> None (uses built-in httpx)."""
        assert create_fetch_provider("default") is None

    def test_creates_jina_with_key(self) -> None:
        provider = create_fetch_provider("jina", api_key="test-key")
        assert isinstance(provider, JinaReaderFetchProvider)

    def test_creates_crawl4ai(self) -> None:
        provider = create_fetch_provider("crawl4ai")
        assert isinstance(provider, Crawl4AIFetchProvider)

    def test_unknown_returns_none(self) -> None:
        assert create_fetch_provider("unknown") is None

    def test_supported_fetch_providers_set(self) -> None:
        assert {"default", "jina", "crawl4ai"} == SUPPORTED_FETCH_PROVIDERS


# ---------------------------------------------------------------------------
# HttpxWebProvider delegation
# ---------------------------------------------------------------------------


class TestHttpxWebProviderDelegation:
    """HttpxWebProvider delegates search() in search_provider."""

    async def test_delegates_search_to_provider(self) -> None:
        """search() delegates in search_provider."""
        expected = [SearchResult(title="Test", url="https://test.com", snippet="snippet")]
        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=expected)

        web = HttpxWebProvider(search_provider=mock_provider)
        results = await web.search("query", max_results=3)

        assert results == expected
        mock_provider.search.assert_called_once_with("query", 3)

    async def test_no_provider_returns_empty(self) -> None:
        """Without search_provider -> empty list."""
        web = HttpxWebProvider()
        results = await web.search("query")
        assert results == []

    async def test_no_provider_explicit_none(self) -> None:
        """YAvnyy None -> empty list."""
        web = HttpxWebProvider(search_provider=None)
        results = await web.search("query")
        assert results == []


# ---------------------------------------------------------------------------
# Executor layer (builtin.py)
# ---------------------------------------------------------------------------


class TestSearchExecutor:
    """search_executor from builtin.py - JSON wrapper for LLM."""

    async def test_empty_query_returns_error(self) -> None:
        """Empty query -> status=error."""
        import json

        from swarmline.tools.builtin import create_web_tools

        mock_web = MagicMock()
        _, executors = create_web_tools(mock_web)
        raw = await executors["web_search"]({"query": ""})
        parsed = json.loads(raw)
        assert parsed["status"] == "error"
        assert "query" in parsed["message"].lower()

    async def test_result_count_in_response(self) -> None:
        """Response contains result_count."""
        import json

        from swarmline.tools.builtin import create_web_tools

        mock_web = AsyncMock()
        mock_web.search = AsyncMock(
            return_value=[
                SearchResult(title="A", url="http://a.com", snippet="a"),
                SearchResult(title="B", url="http://b.com", snippet="b"),
            ]
        )
        _, executors = create_web_tools(mock_web)
        raw = await executors["web_search"]({"query": "test"})
        parsed = json.loads(raw)
        assert parsed["status"] == "ok"
        assert parsed["result_count"] == 2
        assert len(parsed["results"]) == 2

    async def test_exception_returns_error_status(self) -> None:
        """Exception in provaydere -> status=error."""
        import json

        from swarmline.tools.builtin import create_web_tools

        mock_web = AsyncMock()
        mock_web.search = AsyncMock(side_effect=RuntimeError("Network down"))
        _, executors = create_web_tools(mock_web)
        raw = await executors["web_search"]({"query": "test"})
        parsed = json.loads(raw)
        assert parsed["status"] == "error"
        assert "Network down" in parsed["message"]

    async def test_whitespace_query_returns_error(self) -> None:
        """Whitespace-only query → status=error."""
        import json

        from swarmline.tools.builtin import create_web_tools

        mock_web = MagicMock()
        _, executors = create_web_tools(mock_web)
        raw = await executors["web_search"]({"query": "   "})
        parsed = json.loads(raw)
        assert parsed["status"] == "error"


# ---------------------------------------------------------------------------
# _extract_text (web_httpx.py)
# ---------------------------------------------------------------------------


class TestExtractText:
    """_extract_text() - izvlechenie teksta from HTML."""

    def test_removes_script_tags(self) -> None:
        """script tegi polnostyu udalyayutsya (regex fallback)."""
        from swarmline.tools.web_httpx import _extract_text

        html = "<html><body><script>var x = 1;</script><p>Hello</p></body></html>"
        # Prinuditelno otklyuchaem trafilatura chtoby check regex
        with patch("swarmline.tools.web_httpx.trafilatura", None):
            text = _extract_text(html)
        assert "var x" not in text
        assert "Hello" in text

    def test_removes_style_tags(self) -> None:
        """style tegi polnostyu udalyayutsya (regex fallback)."""
        from swarmline.tools.web_httpx import _extract_text

        html = "<html><body><style>.cls { color: red; }</style><p>World</p></body></html>"
        with patch("swarmline.tools.web_httpx.trafilatura", None):
            text = _extract_text(html)
        assert "color" not in text
        assert "World" in text

    def test_removes_html_tags(self) -> None:
        """HTML tegi zamenyayutsya on probely."""
        from swarmline.tools.web_httpx import _extract_text

        html = "<div><h1>Title</h1><p>Content</p></div>"
        text = _extract_text(html)
        assert "Title" in text
        assert "Content" in text
        assert "<" not in text

    def test_limits_output_length(self) -> None:
        """Result ≤ 50000 simvolov."""
        from swarmline.tools.web_httpx import _extract_text

        html = "<p>" + "A" * 100000 + "</p>"
        text = _extract_text(html)
        assert len(text) <= 50000


class TestHttpxWebProviderFetchDelegation:
    """HttpxWebProvider.fetch() delegates in fetch_provider."""

    async def test_delegates_fetch_to_provider(self) -> None:
        """S fetch_provider - delegates."""
        mock_fetch = AsyncMock()
        mock_fetch.fetch = AsyncMock(return_value="# Markdown content")

        web = HttpxWebProvider(fetch_provider=mock_fetch)
        result = await web.fetch("https://example.com")

        assert result == "# Markdown content"
        mock_fetch.fetch.assert_called_once_with("https://example.com")

    async def test_no_fetch_provider_uses_extract_text(self) -> None:
        """Without fetch_provider - _extract_text vyzyvaetsya on html."""
        from swarmline.tools.web_httpx import _extract_text

        html = "<html><body><p>Hello world</p></body></html>"
        with patch("swarmline.tools.web_httpx.trafilatura", None):
            text = _extract_text(html)

        assert "Hello world" in text
        assert "<" not in text
