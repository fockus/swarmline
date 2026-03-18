"""Integration: YamlSkillLoader + SkillRegistry + ToolPolicy - loading and primenotnie skillov. Scenario: load real skilly from skills/, zaregister,
collect MCP-servery and allowlist, check cherez ToolPolicy.
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
    """Load real skilly from proekta."""
    if not SKILLS_DIR.exists():
        pytest.skip("Директория skills/ не найдена")
    loader = YamlSkillLoader(SKILLS_DIR)
    skills = loader.load_all()
    return SkillRegistry(skills)


class TestRealSkillsLoading:
    """Loading realnyh skillov from proekta."""

    def test_skills_loaded(self, registry: SkillRegistry) -> None:
        """Hotya by odin skill zagruzhen."""
        assert len(registry.list_all()) > 0

    def test_iss_skill_present(self, registry: SkillRegistry) -> None:
        """Skill iss zagruzhen."""
        skill = registry.get("iss")
        assert skill is not None
        assert skill.spec.title

    def test_finuslugi_skill_present(self, registry: SkillRegistry) -> None:
        """Skill finuslugi zagruzhen."""
        skill = registry.get("finuslugi")
        assert skill is not None

    def test_iss_has_mcp_servers(self, registry: SkillRegistry) -> None:
        """ISS skill imeet MCP servery."""
        skill = registry.get("iss")
        assert len(skill.spec.mcp_servers) > 0
        assert skill.spec.mcp_servers[0].name == "iss"

    def test_skills_have_instructions(self, registry: SkillRegistry) -> None:
        """Vse skilly imeyut instruktsii."""
        for skill in registry.list_all():
            assert skill.instruction_md, f"Скилл {skill.spec.skill_id} без инструкций"


class TestRegistryAggregation:
    """SkillRegistry sobiraet MCP-servery and allowlist."""

    def test_get_mcp_servers_for_single_skill(self, registry: SkillRegistry) -> None:
        """MCP-servery for odnogo skilla."""
        servers = registry.get_mcp_servers_for_skills(["iss"])
        assert "iss" in servers
        assert servers["iss"].url

    def test_get_mcp_servers_for_multiple_skills(self, registry: SkillRegistry) -> None:
        """MCP-servery for notskolkih skillov - unikalnye by imeni."""
        servers = registry.get_mcp_servers_for_skills(["iss", "finuslugi"])
        assert "iss" in servers
        assert "finuslugi" in servers

    def test_nonexistent_skill_ignored(self, registry: SkillRegistry) -> None:
        """Notsushchestvuyushchiy skill - is ignored."""
        servers = registry.get_mcp_servers_for_skills(["iss", "nonexistent"])
        assert "iss" in servers

    def test_tool_allowlist(self, registry: SkillRegistry) -> None:
        """Allowlist contains tool include from skillov."""
        allowlist = registry.get_tool_allowlist(["iss"])
        assert len(allowlist) > 0


class TestPolicyWithRealSkills:
    """ToolPolicy + real skilly."""

    def test_allow_tool_from_active_skill(self, registry: SkillRegistry) -> None:
        """Tool ot aktivnogo skilla -> allow."""
        policy = DefaultToolPolicy(codec=DefaultToolIdCodec())
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=["iss"],
            allowed_local_tools=set(),
        )
        result = policy.can_use_tool("mcp__iss__get_bonds", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_deny_tool_from_inactive_skill(self, registry: SkillRegistry) -> None:
        """Tool ot notaktivnogo skilla -> deny."""
        policy = DefaultToolPolicy(codec=DefaultToolIdCodec())
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=["finuslugi"],
            allowed_local_tools=set(),
        )
        result = policy.can_use_tool("mcp__iss__get_bonds", {}, state)
        assert isinstance(result, PermissionDeny)
