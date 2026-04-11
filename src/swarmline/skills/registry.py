"""SkillRegistry - registry of loaded skills (SRP: separate from loading)."""

from __future__ import annotations

import structlog

from swarmline.skills.types import LoadedSkill, McpServerSpec

_log = structlog.get_logger(component="skill_registry")


class SkillRegistry:
    """Registry of loaded skills.

    settings_mcp - MCP servers from .claude/settings.json (lower priority).
    On merge: skill.yaml overrides settings.json (§2.1, R-401/R-402).
    """

    def __init__(
        self,
        skills: list[LoadedSkill] | None = None,
        settings_mcp: dict[str, McpServerSpec] | None = None,
    ) -> None:
        self._skills: dict[str, LoadedSkill] = {}
        self._settings_mcp: dict[str, McpServerSpec] = settings_mcp or {}
        if skills:
            for s in skills:
                self._skills[s.spec.skill_id] = s

    def register(self, skill: LoadedSkill) -> None:
        """Register a skill."""
        self._skills[skill.spec.skill_id] = skill

    def get(self, skill_id: str) -> LoadedSkill | None:
        """Get a skill by id."""
        return self._skills.get(skill_id)

    def list_all(self) -> list[LoadedSkill]:
        """All loaded skills."""
        return list(self._skills.values())

    def list_ids(self) -> list[str]:
        """All ids of loaded skills."""
        return list(self._skills.keys())

    def get_mcp_servers_for_skills(self, skill_ids: list[str]) -> dict[str, McpServerSpec]:
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
