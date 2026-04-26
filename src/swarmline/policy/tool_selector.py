"""ToolSelector - smart tool selection under a context budget.

Problem: 40+ tools = 5000-7000 tokens just for schema.
Solution: priority groups + configurable budget.

Everything is configured through ToolBudgetConfig:
- max_tools: overall limit
- group_priority: priority order (overridable)
- group_limits: per-group limit (optional)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from swarmline.runtime.types import ToolSpec


class ToolGroup(IntEnum):
    """Priority tool groups.

    Lower value = higher priority.
    The default order can be overridden via ToolBudgetConfig.group_priority.
    """

    ALWAYS = 0  # thinking, todo - always included
    MCP = 1  # current-role MCP tools - business logic
    MEMORY = 2  # memory_* tools
    PLANNING = 3  # plan_* tools
    SANDBOX = 4  # bash, read, write, edit, ...
    WEB = 5  # web_fetch, web_search


@dataclass(frozen=True)
class ToolBudgetConfig:
    """Tool budget configuration.

    All settings are moved out of hardcode - library users
    control the budget through config.
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
    """Selects tools by priority and budget.

    Fills the budget from top to bottom by groups from config.group_priority.
    If group_limits is set, limits each group.
    """

    def __init__(
        self, config: ToolBudgetConfig | None = None, *, max_tools: int = 30
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = ToolBudgetConfig(max_tools=max_tools)
        self._groups: dict[ToolGroup, list[ToolSpec]] = {}

    def add_group(self, group: ToolGroup, tools: list[ToolSpec]) -> None:
        """Add a tool group."""
        self._groups[group] = tools

    def select(self) -> list[ToolSpec]:
        """Select tools within the budget.

        Returns:
            List of ToolSpec objects sorted by priority from config.
        """
        result: list[ToolSpec] = []
        remaining = self._config.max_tools

        # Traverse groups in the order specified by the config
        for group in self._config.group_priority:
            tools = self._groups.get(group, [])
            if remaining <= 0 or not tools:
                continue

            # Per-group limit (if set)
            group_limit = self._config.group_limits.get(group, remaining)
            take = min(len(tools), remaining, group_limit)

            result.extend(tools[:take])
            remaining -= take

        return result
