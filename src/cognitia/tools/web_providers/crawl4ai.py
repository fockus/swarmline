"""Crawl4AI fetch provider — URL → markdown через Crawl4AI + Playwright.

Optional dependency: crawl4ai (pip install cognitia[web-crawl4ai]).
Использует DefaultMarkdownGenerator для качественной конвертации HTML.
Поддерживает JS-heavy сайты через Playwright.
"""

from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(component="web_fetch.crawl4ai")

try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
except ImportError:
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]
    DefaultMarkdownGenerator = None  # type: ignore[assignment,misc]


class Crawl4AIFetchProvider:
    """Fetch URL через Crawl4AI → markdown с BM25-фильтрацией.

    Crawl4AI использует Playwright для рендеринга JS-heavy страниц
    и DefaultMarkdownGenerator для чистой конвертации HTML → markdown.
    """

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def fetch(self, url: str) -> str:
        """Извлечь контент страницы через Crawl4AI.

        Args:
            url: URL для загрузки.

        Returns:
            Markdown контент. Пустая строка при отсутствии crawl4ai или ошибке.
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
