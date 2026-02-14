"""Протоколы для веб-доступа агента.

WebProvider — ISP-совместимый интерфейс (2 метода) для fetch URL и search.
WebSearchProvider — ISP-совместимый интерфейс (1 метод) для pluggable search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchResult:
    """Результат поиска: title, url, snippet."""

    title: str
    url: str
    snippet: str


@runtime_checkable
class WebSearchProvider(Protocol):
    """Провайдер поиска в интернете (ISP: 1 метод).

    Pluggable: пользователь выбирает реализацию
    (DuckDuckGo, Tavily, SearXNG, Brave Search).
    """

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск в интернете.

        Args:
            query: Поисковый запрос.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult.
        """
        ...


@runtime_checkable
class WebFetchProvider(Protocol):
    """Провайдер извлечения контента из URL (ISP: 1 метод).

    Pluggable: пользователь выбирает реализацию
    (default httpx+trafilatura, Jina Reader, Crawl4AI).
    """

    async def fetch(self, url: str) -> str:
        """Извлечь контент страницы по URL.

        Args:
            url: URL для загрузки.

        Returns:
            Текстовое содержимое (markdown или plain text).
            Пустая строка при ошибке.
        """
        ...


@runtime_checkable
class WebProvider(Protocol):
    """Провайдер веб-доступа для агентов.

    ISP: 2 метода — fetch и search.
    """

    async def fetch(self, url: str) -> str:
        """Получить содержимое URL (HTML → текст/markdown).

        Args:
            url: URL для загрузки.

        Returns:
            Текстовое содержимое страницы.
        """
        ...

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Поиск в интернете.

        Args:
            query: Поисковый запрос.
            max_results: Максимальное количество результатов.

        Returns:
            Список SearchResult.
        """
        ...
