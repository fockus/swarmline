"""Crawl4AI fetch provider - URL -> markdown via Crawl4AI + Playwright.

Optional dependency: crawl4ai (pip install swarmline[web-crawl4ai]).
Uses DefaultMarkdownGenerator for high-quality HTML conversion.
Supports JS-heavy sites via Playwright.
"""

from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(component="web_fetch.crawl4ai")

try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig  # type: ignore[import-not-found]
    from crawl4ai.markdown_generation_strategy import (  # type: ignore[import-not-found]
        DefaultMarkdownGenerator,
    )
except ImportError:
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]
    DefaultMarkdownGenerator = None  # type: ignore[assignment,misc]


class Crawl4AIFetchProvider:
    """Fetch a URL via Crawl4AI -> markdown with BM25 filtering.

    Crawl4AI uses Playwright to render JS-heavy pages
    and DefaultMarkdownGenerator for clean HTML -> markdown conversion.
    """

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def fetch(self, url: str) -> str:
        """Extract page content via Crawl4AI.

        Args:
            url: URL to load.

        Returns:
            Markdown content. Empty string if crawl4ai is unavailable or an error occurs.
        """
        if AsyncWebCrawler is None:
            return ""
        if not url or not url.strip():
            return ""

        try:
            config = CrawlerRunConfig(
                markdown_generator=DefaultMarkdownGenerator(),
            )
            async with AsyncWebCrawler() as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=url.strip(), config=config),
                    timeout=self._timeout,
                )
            if result.success and result.markdown:
                return result.markdown[:50000]
            return ""
        except Exception as exc:
            _log.warning("crawl4ai_fetch_failed", url=url[:200], error=str(exc))
            return ""
