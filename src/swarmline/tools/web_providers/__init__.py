"""Pluggable search and fetch providers for agent web tools.

The user selects a provider via env (WEB_SEARCH_PROVIDER, WEB_FETCH_PROVIDER).
Each provider implements the WebSearchProvider or WebFetchProvider Protocol (ISP: 1 method).

Search providers:
- duckduckgo: metasearch across 9 engines, no API key (default)
- tavily: AI-optimized search (requires TAVILY_API_KEY)
- searxng: self-hosted metasearch engine (requires SEARXNG_URL)
- brave: Brave Search API (requires BRAVE_SEARCH_API_KEY)

Fetch providers:
- default: httpx + trafilatura/regex (built in)
- jina: Jina Reader API -> markdown (requires JINA_API_KEY)
- crawl4ai: Crawl4AI + Playwright -> markdown (pip install crawl4ai)
"""

from swarmline.tools.web_providers.factory import (
    create_fetch_provider,
    create_search_provider,
)

__all__ = ["create_fetch_provider", "create_search_provider"]
