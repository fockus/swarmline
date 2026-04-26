"""Tests ToolBudgetConfig + ToolSelector - TDD."""

from __future__ import annotations

import pytest
from swarmline.runtime.types import ToolSpec


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name, description="d", parameters={"type": "object", "properties": {}}
    )


class TestToolBudgetConfig:
    """Konfig vynosit nastroyki from hardkoda."""

    def test_defaults(self) -> None:
        from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup

        cfg = ToolBudgetConfig()
        assert cfg.max_tools == 30
        assert cfg.group_priority[0] == ToolGroup.ALWAYS
        assert cfg.group_priority[-1] == ToolGroup.WEB
        assert cfg.group_limits == {}

    def test_custom_max_tools(self) -> None:
        from swarmline.policy.tool_selector import ToolBudgetConfig

        cfg = ToolBudgetConfig(max_tools=15)
        assert cfg.max_tools == 15

    def test_custom_priority(self) -> None:
        """User mozhet override poryadok prioritetov."""
        from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup

        cfg = ToolBudgetConfig(
            group_priority=[ToolGroup.MCP, ToolGroup.ALWAYS, ToolGroup.SANDBOX],
        )
        assert cfg.group_priority[0] == ToolGroup.MCP

    def test_group_limits(self) -> None:
        """Per-group limity."""
        from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup

        cfg = ToolBudgetConfig(group_limits={ToolGroup.SANDBOX: 3, ToolGroup.MCP: 10})
        assert cfg.group_limits[ToolGroup.SANDBOX] == 3

    def test_frozen(self) -> None:
        from swarmline.policy.tool_selector import ToolBudgetConfig

        cfg = ToolBudgetConfig()
        with pytest.raises(AttributeError):
            cfg.max_tools = 99  # type: ignore[misc]


class TestToolSelector:
    """ToolSelector - otbiraet tools by konfigu."""

    def test_always_tools_included(self) -> None:
        from swarmline.policy.tool_selector import ToolGroup, ToolSelector

        selector = ToolSelector(max_tools=5)
        selector.add_group(
            ToolGroup.ALWAYS,
            [_spec("thinking"), _spec("todo_read"), _spec("todo_write")],
        )
        selector.add_group(
            ToolGroup.SANDBOX, [_spec("bash"), _spec("read"), _spec("write")]
        )

        selected = selector.select()
        names = {s.name for s in selected}
        assert "thinking" in names
        assert "todo_read" in names

    def test_budget_limits_total(self) -> None:
        from swarmline.policy.tool_selector import ToolGroup, ToolSelector

        selector = ToolSelector(max_tools=3)
        selector.add_group(ToolGroup.ALWAYS, [_spec("thinking")])
        selector.add_group(ToolGroup.SANDBOX, [_spec(f"s{i}") for i in range(10)])

        selected = selector.select()
        assert len(selected) <= 3

    def test_mcp_gets_priority_after_always(self) -> None:
        from swarmline.policy.tool_selector import ToolGroup, ToolSelector

        selector = ToolSelector(max_tools=5)
        selector.add_group(ToolGroup.ALWAYS, [_spec("thinking")])
        selector.add_group(ToolGroup.MCP, [_spec("mcp_search"), _spec("mcp_get")])
        selector.add_group(
            ToolGroup.SANDBOX,
            [_spec("bash"), _spec("read"), _spec("write"), _spec("edit")],
        )

        selected = selector.select()
        names = [s.name for s in selected]
        assert "thinking" in names
        assert "mcp_search" in names
        assert "mcp_get" in names
        assert len(selected) == 5

    def test_config_based_selector(self) -> None:
        """ToolSelector with yavnym config."""
        from swarmline.policy.tool_selector import (
            ToolBudgetConfig,
            ToolGroup,
            ToolSelector,
        )

        cfg = ToolBudgetConfig(max_tools=4, group_limits={ToolGroup.SANDBOX: 2})
        selector = ToolSelector(config=cfg)
        selector.add_group(ToolGroup.ALWAYS, [_spec("thinking")])
        selector.add_group(
            ToolGroup.SANDBOX,
            [_spec("bash"), _spec("read"), _spec("write"), _spec("edit")],
        )

        selected = selector.select()
        names = [s.name for s in selected]
        # thinking (1) + sandbox limited to 2 = 3 total
        assert "thinking" in names
        assert (
            len([n for n in names if n.startswith(("bash", "read", "write", "edit"))])
            <= 2
        )

    def test_custom_priority_order(self) -> None:
        """Kastomnyy poryadok: SANDBOX pered MCP."""
        from swarmline.policy.tool_selector import (
            ToolBudgetConfig,
            ToolGroup,
            ToolSelector,
        )

        cfg = ToolBudgetConfig(
            max_tools=3,
            group_priority=[ToolGroup.SANDBOX, ToolGroup.MCP],
        )
        selector = ToolSelector(config=cfg)
        selector.add_group(ToolGroup.MCP, [_spec("mcp_a"), _spec("mcp_b")])
        selector.add_group(ToolGroup.SANDBOX, [_spec("bash"), _spec("read")])

        selected = selector.select()
        names = [s.name for s in selected]
        # Sandbox pervyy by kastomnomu prioritetu
        assert names[0] == "bash"
        assert names[1] == "read"
        assert len(selected) == 3

    def test_empty_groups(self) -> None:
        from swarmline.policy.tool_selector import ToolSelector

        selector = ToolSelector(max_tools=10)
        assert selector.select() == []

    def test_priority_order(self) -> None:
        from swarmline.policy.tool_selector import ToolGroup

        assert ToolGroup.ALWAYS.value < ToolGroup.MCP.value
        assert ToolGroup.MCP.value < ToolGroup.MEMORY.value
        assert ToolGroup.MEMORY.value < ToolGroup.PLANNING.value
        assert ToolGroup.PLANNING.value < ToolGroup.SANDBOX.value
        assert ToolGroup.SANDBOX.value < ToolGroup.WEB.value

    def test_all_fit_in_budget(self) -> None:
        from swarmline.policy.tool_selector import ToolGroup, ToolSelector

        selector = ToolSelector(max_tools=50)
        selector.add_group(ToolGroup.ALWAYS, [_spec("thinking")])
        selector.add_group(ToolGroup.MCP, [_spec("mcp_a"), _spec("mcp_b")])
        selector.add_group(ToolGroup.SANDBOX, [_spec("bash"), _spec("read")])

        selected = selector.select()
        assert len(selected) == 5
