"""SearXNG search provider - self-hosted metasearch engine.

Requires a SearXNG instance URL (SEARXNG_URL).
Dependency: httpx (already included in swarmline[web]).
"""

from __future__ import annotations

import httpx
import structlog

from swarmline.tools.web_protocols import SearchResult

_log = structlog.get_logger(component="web_search.searxng")


class SearXNGSearchProvider:
    """Search via SearXNG (self-hosted, no limits).

    Connects to a user-provided SearXNG instance by URL.
    """

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        if not base_url:
            raise ValueError("SEARXNG_URL обязателен для SearXNGSearchProvider")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via the SearXNG JSON API.

        Args:
            query: Search query. Empty/whitespace -> empty list.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult. Empty on connection error.
        """
        if not query or not query.strip():
            return []

        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "pageno": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/search",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            _log.warning("searxng_search_failed", query=query[:100], error=str(exc))
            return []

        results = data.get("results", [])[:max_results]
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in results
        ]
