"""SkillRegistry - registry of loaded skills (SRP: separate from loading).

Implements SkillStore Protocol (phase 58): search(), health management, tier filtering.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import structlog

from swarmline.skills.protocols import ScoredSkill
from swarmline.skills.tier import SkillHealthStatus, SkillTier
from swarmline.skills.types import LoadedSkill, McpServerSpec, SkillSpec

if TYPE_CHECKING:
    from swarmline.skills.protocols import SkillRetriever

_log = structlog.get_logger(component="skill_registry")


class SkillRegistry:
    """Registry of loaded skills.

    settings_mcp - MCP servers from .claude/settings.json (lower priority).
    On merge: skill.yaml overrides settings.json (§2.1, R-401/R-402).

    Satisfies SkillStore Protocol: get(), list_all() (returns LoadedSkill
    which is a superset), search().
    """

    def __init__(
        self,
        skills: list[LoadedSkill] | None = None,
        settings_mcp: dict[str, McpServerSpec] | None = None,
    ) -> None:
        self._skills: dict[str, LoadedSkill] = {}
        self._settings_mcp: dict[str, McpServerSpec] = settings_mcp or {}
        self._retriever: SkillRetriever | None = None
        if skills:
            for s in skills:
                self._skills[s.spec.skill_id] = s

    def set_retriever(self, retriever: SkillRetriever) -> None:
        """Set the skill retriever for semantic search."""
        self._retriever = retriever

    def register(self, skill: LoadedSkill) -> None:
        """Register a skill."""
        self._skills[skill.spec.skill_id] = skill

    def get(self, skill_id: str) -> LoadedSkill | None:
        """Get a loaded skill by id (includes instruction_md)."""
        return self._skills.get(skill_id)

    def get_spec(self, skill_id: str) -> SkillSpec | None:
        """Get a skill spec by id (SkillStore Protocol)."""
        loaded = self._skills.get(skill_id)
        return loaded.spec if loaded else None

    def list_all(self) -> list[LoadedSkill]:
        """All loaded skills (includes instruction_md)."""
        return list(self._skills.values())

    def list_specs(self) -> list[SkillSpec]:
        """All skill specs (SkillStore Protocol)."""
        return [s.spec for s in self._skills.values()]

    def list_ids(self) -> list[str]:
        """All ids of loaded skills."""
        return list(self._skills.keys())

    def search(self, query: str, top_k: int = 5) -> list[ScoredSkill]:
        """Search skills by query.

        Delegates to retriever if set; otherwise returns all skills as ScoredSkill.
        """
        specs = [s.spec for s in self._skills.values()]
        if self._retriever is not None:
            return self._retriever.retrieve(query, specs, top_k)
        return [
            ScoredSkill(skill=spec, score=0.0, source="registry")
            for spec in specs[:top_k]
        ]

    def update_health(self, skill_id: str, status: SkillHealthStatus) -> None:
        """Update the health status of a skill.

        When status becomes UNAVAILABLE, tier is automatically downgraded to T4_DISABLED.
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            _log.warning("update_health_unknown_skill", skill_id=skill_id)
            return
        new_tier = skill.spec.tier
        if status == SkillHealthStatus.UNAVAILABLE:
            new_tier = SkillTier.T4_DISABLED
        new_spec = replace(skill.spec, health_status=status, tier=new_tier)
        self._skills[skill_id] = LoadedSkill(
            spec=new_spec, instruction_md=skill.instruction_md
        )

    def get_health_report(self) -> dict[str, SkillHealthStatus]:
        """Return health status for every registered skill."""
        return {sid: s.spec.health_status for sid, s in self._skills.items()}

    def filter_by_tier(self, max_tier: SkillTier) -> list[LoadedSkill]:
        """Return skills whose tier is at or below max_tier."""
        return [s for s in self._skills.values() if s.spec.tier <= max_tier]

    def get_mcp_servers_for_skills(
        self, skill_ids: list[str]
    ) -> dict[str, McpServerSpec]:
        """Collect MCP servers for a set of skills (§4.3, R-401/R-402).

        Merge policy: settings.json (lower priority) + skill.yaml (upper priority).
        skill.yaml overrides settings.json when names match.
        """
        # Base layer - MCP from settings.json
        servers: dict[str, McpServerSpec] = dict(self._settings_mcp)

        # Upper layer - MCP from skill.yaml (overrides)
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if not skill:
                continue
            for srv in skill.spec.mcp_servers:
                servers[srv.name] = srv
        return servers

    def get_tool_allowlist(self, skill_ids: list[str]) -> set[str]:
        """Collect tool id allowlists for a set of skills."""
        tools: set[str] = set()
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if not skill:
                continue
            tools.update(skill.spec.tool_include)
            tools.update(skill.spec.local_tools)
        return tools

    def get_tool_descriptions(self, skill_ids: list[str]) -> dict[str, str]:
        """Map tool names to descriptions for discovered skills.

        Returns tool_name → description based on the skill's description
        and title. Used by ProactiveSkillInjector to populate ToolSpec metadata.
        """
        result: dict[str, str] = {}
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if not skill:
                continue
            desc = skill.spec.description or skill.spec.title
            for tool_name in skill.spec.tool_include:
                if tool_name not in result:
                    result[tool_name] = f"[{skill.spec.title}] {desc}"
            for tool_name in skill.spec.local_tools:
                if tool_name not in result:
                    result[tool_name] = f"[{skill.spec.title}] {desc}"
        return result

    def validate_tools(self, available_tools: set[str]) -> list[str]:
        """Check that tools.include from skill.yaml are available (§4.4 acceptance).

        Args:
            available_tools: the set of tool names actually available from SDK/MCP.

        Returns:
            A list of warnings about unavailable tools.
        """
        warnings: list[str] = []
        for skill in self._skills.values():
            for tool_name in skill.spec.tool_include:
                if tool_name not in available_tools:
                    msg = (
                        f"Skill '{skill.spec.skill_id}': инструмент "
                        f"'{tool_name}' не найден среди доступных MCP tools"
                    )
                    warnings.append(msg)
                    _log.warning(
                        "tool_not_available",
                        skill_id=skill.spec.skill_id,
                        tool_name=tool_name,
                    )
        if not warnings:
            _log.info(
                "tools_validated",
                total_skills=len(self._skills),
                status="all_tools_available",
            )
        return warnings
