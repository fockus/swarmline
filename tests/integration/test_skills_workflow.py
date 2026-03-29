"""Integration: YamlSkillLoader + SkillRegistry + ToolPolicy — loading and applying skills.

Scenario: load real skills from skills/, register, collect MCP servers and allowlist,
check via ToolPolicy.
"""

from pathlib import Path

import pytest
from cognitia.policy.tool_id_codec import DefaultToolIdCodec
from cognitia.policy.tool_policy import (
    DefaultToolPolicy,
    PermissionAllow,
    PermissionDeny,
    ToolPolicyInput,
)
from cognitia.skills.loader import YamlSkillLoader
from cognitia.skills.registry import SkillRegistry

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


@pytest.fixture
def registry() -> SkillRegistry:
    """Load real skills from project."""
    if not SKILLS_DIR.exists():
        pytest.skip("Directory skills/ not found")
    loader = YamlSkillLoader(SKILLS_DIR)
    skills = loader.load_all()
    return SkillRegistry(skills)


class TestRealSkillsLoading:
    """Loading real skills from the project."""

    def test_skills_loaded(self, registry: SkillRegistry) -> None:
        """At least one skill is loaded."""
        assert len(registry.list_all()) > 0

    def test_cognitia_agents_skill_present(self, registry: SkillRegistry) -> None:
        """Skill cognitia-agents is loaded."""
        skill = registry.get("cognitia-agents")
        assert skill is not None
        assert skill.spec.title

    def test_cognitia_agents_has_mcp_servers(self, registry: SkillRegistry) -> None:
        """cognitia-agents skill has MCP servers."""
        skill = registry.get("cognitia-agents")
        assert skill is not None
        assert len(skill.spec.mcp_servers) > 0
        assert skill.spec.mcp_servers[0].name == "cognitia"

    def test_skills_have_instructions(self, registry: SkillRegistry) -> None:
        """All skills have instruction content."""
        for skill in registry.list_all():
            assert skill.instruction_md, f"Skill {skill.spec.skill_id} has no instructions"


class TestRegistryAggregation:
    """SkillRegistry collects MCP servers and allowlists."""

    def test_get_mcp_servers_for_single_skill(self, registry: SkillRegistry) -> None:
        """MCP servers for a single skill."""
        servers = registry.get_mcp_servers_for_skills(["cognitia-agents"])
        assert "cognitia" in servers

    def test_nonexistent_skill_ignored(self, registry: SkillRegistry) -> None:
        """Non-existent skill is ignored without error."""
        servers = registry.get_mcp_servers_for_skills(["cognitia-agents", "nonexistent"])
        assert "cognitia" in servers


class TestPolicyWithRealSkills:
    """ToolPolicy + real skills."""

    def test_allow_tool_from_active_skill(self, registry: SkillRegistry) -> None:
        """Tool from active MCP server -> allow."""
        policy = DefaultToolPolicy(codec=DefaultToolIdCodec())
        # Policy checks server_name against active_skill_ids,
        # so we pass the MCP server name ("cognitia"), not the skill ID
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=["cognitia"],
            allowed_local_tools=set(),
        )
        result = policy.can_use_tool("mcp__cognitia__memory_upsert_fact", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_deny_tool_from_inactive_skill(self, registry: SkillRegistry) -> None:
        """Tool from inactive MCP server -> deny."""
        policy = DefaultToolPolicy(codec=DefaultToolIdCodec())
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=[],
            allowed_local_tools=set(),
        )
        result = policy.can_use_tool("mcp__cognitia__memory_upsert_fact", {}, state)
        assert isinstance(result, PermissionDeny)
