"""Unit-tests for SkillRegistry.validate_tools (§4.4)."""

from __future__ import annotations

from swarmline.skills.registry import SkillRegistry
from swarmline.skills.types import LoadedSkill, SkillSpec


def _make_skill(skill_id: str, tools: list[str]) -> LoadedSkill:
    spec = SkillSpec(
        skill_id=skill_id,
        title=skill_id,
        instruction_file="",
        tool_include=tools,
    )
    return LoadedSkill(spec=spec, instruction_md="")


class TestValidateTools:
    """Tests startup self-check (§4.4)."""

    def test_all_tools_available(self) -> None:
        """Vse tools available -> nott preduprezhdeniy."""
        registry = SkillRegistry(
            [
                _make_skill("iss", ["mcp__iss__get_market_snapshot"]),
                _make_skill("finuslugi", ["mcp__finuslugi__get_bank_deposits"]),
            ]
        )
        available = {"mcp__iss__get_market_snapshot", "mcp__finuslugi__get_bank_deposits"}
        warnings = registry.validate_tools(available)
        assert warnings == []

    def test_missing_tool_warning(self) -> None:
        """Notavailable tool -> preduprezhdenie."""
        registry = SkillRegistry(
            [
                _make_skill("iss", ["mcp__iss__get_market_snapshot", "mcp__iss__missing_tool"]),
            ]
        )
        available = {"mcp__iss__get_market_snapshot"}
        warnings = registry.validate_tools(available)
        assert len(warnings) == 1
        assert "missing_tool" in warnings[0]
        assert "iss" in warnings[0]

    def test_empty_registry(self) -> None:
        """Empty reestr -> nott preduprezhdeniy."""
        registry = SkillRegistry([])
        warnings = registry.validate_tools(set())
        assert warnings == []

    def test_multiple_skills_multiple_warnings(self) -> None:
        """Notskolko skilov with notavailablemi tools."""
        registry = SkillRegistry(
            [
                _make_skill("iss", ["mcp__iss__missing1"]),
                _make_skill("funds", ["mcp__funds__missing2"]),
            ]
        )
        warnings = registry.validate_tools(set())
        assert len(warnings) == 2
