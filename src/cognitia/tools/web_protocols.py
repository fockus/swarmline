"""Протоколы для веб-доступа агента.

WebProvider — ISP-совместимый интерфейс (2 метода) для fetch URL и search.
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
