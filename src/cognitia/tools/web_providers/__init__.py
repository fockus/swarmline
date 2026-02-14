"""Pluggable search и fetch providers для веб-инструментов агентов.

Пользователь выбирает провайдер через env (WEB_SEARCH_PROVIDER, WEB_FETCH_PROVIDER).
Каждый провайдер реализует WebSearchProvider или WebFetchProvider Protocol (ISP: 1 метод).

Search провайдеры:
- duckduckgo: метапоиск по 9 движкам, без API key (default)
- tavily: AI-оптимизированный поиск (требует TAVILY_API_KEY)
- searxng: self-hosted метапоисковик (требует SEARXNG_URL)
- brave: Brave Search API (требует BRAVE_SEARCH_API_KEY)

Fetch провайдеры:
- default: httpx + trafilatura/regex (встроенный)
- jina: Jina Reader API → markdown (требует JINA_API_KEY)
- crawl4ai: Crawl4AI + Playwright → markdown (pip install crawl4ai)
"""

from cognitia.tools.web_providers.factory import create_fetch_provider, create_search_provider

__all__ = ["create_fetch_provider", "create_search_provider"]
