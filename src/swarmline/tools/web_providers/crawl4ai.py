"""Crawl4AI fetch provider - URL -> markdown via Crawl4AI + Playwright.

Optional dependency: crawl4ai (pip install swarmline[web-crawl4ai]).
Uses DefaultMarkdownGenerator for high-quality HTML conversion.
Supports JS-heavy sites via Playwright.
"""

from __future__ import annotations

import asyncio

import structlog

from swarmline.network_safety import validate_http_endpoint_url
from swarmline.observability.redaction import redact_secrets

_log = structlog.get_logger(component="web_fetch.crawl4ai")

try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig  # ty: ignore[unresolved-import]  # optional dep
    from crawl4ai.markdown_generation_strategy import (  # ty: ignore[unresolved-import]  # optional dep
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
        if not url or not url.strip():
            return ""
        normalized_url = url.strip()
        log_url = redact_secrets(normalized_url)[:200]
        rejection = validate_http_endpoint_url(normalized_url)
        if rejection:
            _log.warning(
                "crawl4ai_fetch_url_denied",
                url=log_url,
                reason=rejection,
            )
            return ""
        if AsyncWebCrawler is None:
            return ""

        try:
            config = CrawlerRunConfig(  # ty: ignore[call-non-callable]  # gated by AsyncWebCrawler is None check above
                markdown_generator=DefaultMarkdownGenerator(),  # ty: ignore[call-non-callable]  # gated by AsyncWebCrawler is None check above
            )
            async with AsyncWebCrawler() as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=normalized_url, config=config),
                    timeout=self._timeout,
                )
            if result.success and result.markdown:
                return result.markdown[:50000]
            return ""
        except Exception as exc:
            _log.warning(
                "crawl4ai_fetch_failed",
                url=log_url,
                error=redact_secrets(str(exc)),
            )
            return ""
