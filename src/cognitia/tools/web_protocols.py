"""Protocols for agent web access.

WebProvider is an ISP-compliant interface (2 methods) for URL fetch and search.
WebSearchProvider is an ISP-compliant interface (1 method) for pluggable search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchResult:
    """Search result: title, url, snippet."""

    title: str
    url: str
    snippet: str


@runtime_checkable
class WebSearchProvider(Protocol):
    """Internet search provider (ISP: 1 method).

    Pluggable: the user selects an implementation
    (DuckDuckGo, Tavily, SearXNG, Brave Search).
    """

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search the internet.

        Args:
            query: Search query.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult.
        """
        ...


@runtime_checkable
class WebFetchProvider(Protocol):
    """URL content extraction provider (ISP: 1 method).

    Pluggable: the user selects an implementation
    (default httpx+trafilatura, Jina Reader, Crawl4AI).
    """

    async def fetch(self, url: str) -> str:
        """Extract page content by URL.

        Args:
            url: URL to load.

        Returns:
            Text content (markdown or plain text).
            Empty string on error.
        """
        ...


@runtime_checkable
class WebProvider(Protocol):
    """Web access provider for agents.

    ISP: 2 methods - fetch and search.
    """

    async def fetch(self, url: str) -> str:
        """Get URL content (HTML → text/markdown).

        Args:
            url: URL to load.

        Returns:
            Page content text.
        """
        ...

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search the internet.

        Args:
            query: Search query.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult.
        """
        ...
