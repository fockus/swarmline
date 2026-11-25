"""Tests for ContextBridge dataclass and builder."""

from __future__ import annotations

import pytest
from swarmline.orchestration.context_bridge import (
    ContextBridge,
    ContextBridgeBuilder,
)

# ---------------------------------------------------------------------------
# ContextBridge frozen dataclass
# ---------------------------------------------------------------------------


class TestContextBridge:
    """ContextBridge immutability and field tests."""

    def test_context_bridge_all_fields_set(self) -> None:
        cb = ContextBridge(
            parent_goal="solve puzzle",
            parent_progress="50% done",
            parent_findings=["fact1", "fact2"],
            inherited_tools=["tool_a"],
            max_turns=5,
        )
        assert cb.parent_goal == "solve puzzle"
        assert cb.parent_progress == "50% done"
        assert cb.parent_findings == ["fact1", "fact2"]
        assert cb.inherited_tools == ["tool_a"]
        assert cb.max_turns == 5

    def test_context_bridge_max_turns_defaults_to_ten(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        assert cb.max_turns == 10

    def test_context_bridge_frozen_rejects_mutation(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        with pytest.raises(AttributeError):
            cb.parent_goal = "changed"  # type: ignore[misc]

    def test_context_bridge_equality(self) -> None:
        kwargs = {
            "parent_goal": "g",
            "parent_progress": "p",
            "parent_findings": ["f"],
            "inherited_tools": ["t"],
            "max_turns": 3,
        }
        assert ContextBridge(**kwargs) == ContextBridge(**kwargs)


# ---------------------------------------------------------------------------
# ContextBridgeBuilder
# ---------------------------------------------------------------------------


class TestContextBridgeBuilder:
    """Builder static methods tests."""

    def test_from_agent_state_creates_bridge(self) -> None:
        cb = ContextBridgeBuilder.from_agent_state(
            goal="research topic",
            progress="started",
            findings=["finding1"],
            tools=["web_search"],
        )
        assert isinstance(cb, ContextBridge)
        assert cb.parent_goal == "research topic"
        assert cb.parent_progress == "started"
        assert cb.parent_findings == ["finding1"]
        assert cb.inherited_tools == ["web_search"]
        assert cb.max_turns == 10

    def test_from_agent_state_with_max_turns(self) -> None:
        cb = ContextBridgeBuilder.from_agent_state(
            goal="g",
            progress="p",
            findings=[],
            tools=[],
            max_turns=20,
        )
        assert cb.max_turns == 20

    def test_format_for_prompt_contains_goal(self) -> None:
        cb = ContextBridge(
            parent_goal="find answer",
            parent_progress="searching",
            parent_findings=["clue1"],
            inherited_tools=["tool_x"],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "find answer" in text

    def test_format_for_prompt_contains_progress(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="halfway there",
            parent_findings=[],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "halfway there" in text

    def test_format_for_prompt_contains_findings(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=["discovery A", "discovery B"],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "discovery A" in text
        assert "discovery B" in text

    def test_format_for_prompt_returns_nonempty_string(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert isinstance(text, str)
        assert len(text) > 10

    def test_format_for_prompt_empty_findings_no_crash(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert isinstance(text, str)

    def test_format_for_prompt_includes_all_sections(self) -> None:
        cb = ContextBridge(
            parent_goal="solve the puzzle",
            parent_progress="halfway done",
            parent_findings=["clue A", "clue B"],
            inherited_tools=["search", "calculator"],
            max_turns=15,
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "solve the puzzle" in text
        assert "halfway done" in text
        assert "clue A" in text
        assert "clue B" in text
        assert "search" in text
        assert "calculator" in text
        assert "15" in text
        assert "Parent Context" in text

    def test_format_for_prompt_empty_findings_omits_findings_header(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "Findings" not in text

    def test_format_for_prompt_empty_tools_omits_tools_line(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "Available tools" not in text

    def test_format_for_prompt_with_tools_shows_tools(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=["web_search", "code_exec"],
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "web_search" in text
        assert "code_exec" in text
        assert "Available tools" in text

    def test_format_for_prompt_turn_budget_always_present(self) -> None:
        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
            max_turns=7,
        )
        text = ContextBridgeBuilder.format_for_prompt(cb)
        assert "Turn budget" in text
        assert "7" in text

    def test_from_agent_state_copies_lists_defensively(self) -> None:
        findings = ["f1", "f2"]
        tools = ["t1"]
        cb = ContextBridgeBuilder.from_agent_state(
            goal="g",
            progress="p",
            findings=findings,
            tools=tools,
        )
        findings.append("f3")
        tools.append("t2")
        assert cb.parent_findings == ["f1", "f2"]
        assert cb.inherited_tools == ["t1"]


# ---------------------------------------------------------------------------
# SubagentSpec backward compatibility
# ---------------------------------------------------------------------------


class TestSubagentSpecContextBridge:
    """SubagentSpec with optional context_bridge field."""

    def test_subagent_spec_context_bridge_defaults_none(self) -> None:
        from swarmline.orchestration.subagent_types import SubagentSpec

        spec = SubagentSpec(name="test", system_prompt="do stuff")
        assert spec.context_bridge is None

    def test_subagent_spec_with_context_bridge(self) -> None:
        from swarmline.orchestration.subagent_types import SubagentSpec

        cb = ContextBridge(
            parent_goal="g",
            parent_progress="p",
            parent_findings=[],
            inherited_tools=[],
        )
        spec = SubagentSpec(name="test", system_prompt="do stuff", context_bridge=cb)
        assert spec.context_bridge is cb
