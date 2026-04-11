"""Brave Search provider - 2000 req/month free.

Requires an API key (BRAVE_SEARCH_API_KEY).
Dependency: httpx (already included in swarmline[web]).
API docs: https://api.search.brave.com/app/documentation/web-search
"""

from __future__ import annotations

import httpx
import structlog

from swarmline.tools.web_protocols import SearchResult

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_log = structlog.get_logger(component="web_search.brave")


class BraveSearchProvider:
    """Search via the Brave Search API (free tier: 2000 req/month).

    Requires an API key. Uses httpx for HTTP requests.
    """

    def __init__(self, api_key: str, timeout: int = 15) -> None:
        if not api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY обязателен для BraveSearchProvider")
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via the Brave Search API.

        Args:
            query: Search query. Empty/whitespace -> empty list.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult. Empty on error.
        """
        if not query or not query.strip():
            return []

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params: dict[str, str] = {
            "q": query,
            "count": str(max_results),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    _BRAVE_SEARCH_URL,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            _log.warning("brave_search_failed", query=query[:100], error=str(exc))
            return []

        web_results = data.get("web", {}).get("results", [])[:max_results]
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in web_results
        ]
