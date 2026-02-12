"""ToolSelector — умный отбор инструментов под бюджет контекста.

Проблема: 40+ tools = 5000-7000 токенов только на schema.
Решение: приоритетные группы + конфигурируемый бюджет.

Всё настраивается через ToolBudgetConfig:
- max_tools: общий лимит
- group_priority: порядок приоритетов (можно переопределить)
- group_limits: лимит per-group (опционально)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from cognitia.runtime.types import ToolSpec


class ToolGroup(IntEnum):
    """Приоритетные группы инструментов.

    Меньше значение = выше приоритет.
    Дефолтный порядок переопределяется через ToolBudgetConfig.group_priority.
    """

    ALWAYS = 0    # thinking, todo — всегда включены
    MCP = 1       # MCP tools текущей роли — бизнес-логика
    MEMORY = 2    # memory_* tools
    PLANNING = 3  # plan_* tools
    SANDBOX = 4   # bash, read, write, edit, ...
    WEB = 5       # web_fetch, web_search


@dataclass(frozen=True)
class ToolBudgetConfig:
    """Конфигурация бюджета инструментов.

    Все настройки вынесены из хардкода — пользователь библиотеки
    контролирует бюджет через конфиг.
    """

    max_tools: int = 30
    group_priority: list[ToolGroup] = field(
        default_factory=lambda: [
            ToolGroup.ALWAYS,
            ToolGroup.MCP,
            ToolGroup.MEMORY,
            ToolGroup.PLANNING,
            ToolGroup.SANDBOX,
            ToolGroup.WEB,
        ]
    )
    group_limits: dict[ToolGroup, int] = field(default_factory=dict)


class ToolSelector:
    """Отбирает tools по приоритету и бюджету.

    Заполняет бюджет сверху вниз по группам из config.group_priority.
    Если group_limits задан — ограничивает per-group.
    """

    def __init__(self, config: ToolBudgetConfig | None = None, *, max_tools: int = 30) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = ToolBudgetConfig(max_tools=max_tools)
        self._groups: dict[ToolGroup, list[ToolSpec]] = {}

    def add_group(self, group: ToolGroup, tools: list[ToolSpec]) -> None:
        """Добавить группу инструментов."""
        self._groups[group] = tools

    def select(self) -> list[ToolSpec]:
        """Отобрать инструменты в рамках бюджета.

        Returns:
            Список ToolSpec, отсортированный по приоритету из config.
        """
        result: list[ToolSpec] = []
        remaining = self._config.max_tools

        # Обходим группы в порядке приоритета из конфига
        for group in self._config.group_priority:
            tools = self._groups.get(group, [])
            if remaining <= 0 or not tools:
                continue

            # Per-group лимит (если задан)
            group_limit = self._config.group_limits.get(group, remaining)
            take = min(len(tools), remaining, group_limit)

            result.extend(tools[:take])
            remaining -= take

        return result
