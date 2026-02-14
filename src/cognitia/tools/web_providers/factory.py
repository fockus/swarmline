"""Factory для создания search/fetch provider по имени (OCP).

Новый провайдер = новый файл в web_providers/ + ветка в factory.
Существующие провайдеры не меняются.
"""

from __future__ import annotations

from cognitia.tools.web_protocols import WebFetchProvider, WebSearchProvider

# Допустимые имена провайдеров
SUPPORTED_SEARCH_PROVIDERS = frozenset({"duckduckgo", "tavily", "searxng", "brave"})
SUPPORTED_FETCH_PROVIDERS = frozenset({"default", "jina", "crawl4ai"})

# Backward compat
SUPPORTED_PROVIDERS = SUPPORTED_SEARCH_PROVIDERS


def create_search_provider(
    provider_name: str,
    *,
    api_key: str = "",
    base_url: str = "",
) -> WebSearchProvider | None:
    """Создать search provider по имени.

    Args:
        provider_name: Имя провайдера (duckduckgo, tavily, searxng, brave).
        api_key: API ключ (для tavily, brave).
        base_url: URL инстанса (для searxng).

    Returns:
        WebSearchProvider или None если провайдер неизвестен.
    """
    if provider_name == "duckduckgo":
        from cognitia.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        return DuckDuckGoSearchProvider()

    if provider_name == "tavily":
        from cognitia.tools.web_providers.tavily import TavilySearchProvider

        return TavilySearchProvider(api_key=api_key)

    if provider_name == "searxng":
        from cognitia.tools.web_providers.searxng import SearXNGSearchProvider

        return SearXNGSearchProvider(base_url=base_url)

    if provider_name == "brave":
        from cognitia.tools.web_providers.brave import BraveSearchProvider

        return BraveSearchProvider(api_key=api_key)

    return None


def create_fetch_provider(
    provider_name: str,
    *,
    api_key: str = "",
) -> WebFetchProvider | None:
    """Создать fetch provider по имени.

    Args:
        provider_name: Имя провайдера (default, jina, crawl4ai).
        api_key: API ключ (для jina).

    Returns:
        WebFetchProvider или None если 'default' или неизвестен.
        'default' -> None означает использование встроенного httpx+trafilatura.
    """
    if provider_name == "default":
        return None

    if provider_name == "jina":
        from cognitia.tools.web_providers.jina import JinaReaderFetchProvider

        return JinaReaderFetchProvider(api_key=api_key)

    if provider_name == "crawl4ai":
        from cognitia.tools.web_providers.crawl4ai import Crawl4AIFetchProvider

        return Crawl4AIFetchProvider()

    return None
