"""Factory for creating search/fetch providers by name (OCP).

New provider = new file in web_providers/ + a branch in factory.
Existing providers are not modified.
"""

from __future__ import annotations

from swarmline.tools.web_protocols import WebFetchProvider, WebSearchProvider

# Allowed provider names
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
    """Create a search provider by name.

    Args:
        provider_name: Provider name (duckduckgo, tavily, searxng, brave).
        api_key: API key (for tavily, brave).
        base_url: Instance URL (for searxng).

    Returns:
        WebSearchProvider or None if the provider is unknown.
    """
    if provider_name == "duckduckgo":
        from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

        return DuckDuckGoSearchProvider()

    if provider_name == "tavily":
        from swarmline.tools.web_providers.tavily import TavilySearchProvider

        return TavilySearchProvider(api_key=api_key)

    if provider_name == "searxng":
        from swarmline.tools.web_providers.searxng import SearXNGSearchProvider

        return SearXNGSearchProvider(base_url=base_url)

    if provider_name == "brave":
        from swarmline.tools.web_providers.brave import BraveSearchProvider

        return BraveSearchProvider(api_key=api_key)

    return None


def create_fetch_provider(
    provider_name: str,
    *,
    api_key: str = "",
) -> WebFetchProvider | None:
    """Create a fetch provider by name.

    Args:
        provider_name: Provider name (default, jina, crawl4ai).
        api_key: API key (for jina).

    Returns:
        WebFetchProvider or None if 'default' or unknown.
        'default' -> None means using the built-in httpx+trafilatura path.
    """
    if provider_name == "default":
        return None

    if provider_name == "jina":
        from swarmline.tools.web_providers.jina import JinaReaderFetchProvider

        return JinaReaderFetchProvider(api_key=api_key)

    if provider_name == "crawl4ai":
        from swarmline.tools.web_providers.crawl4ai import Crawl4AIFetchProvider

        return Crawl4AIFetchProvider()

    return None
