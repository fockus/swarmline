"""Data types for the skills system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

McpTransport = Literal["url", "http", "sse", "stdio"]


@dataclass(frozen=True)
class McpServerSpec:
    """MCP server specification."""

    name: str
    transport: McpTransport = "url"
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class SkillSpec:
    """Skill specification (from YAML or SKILL.md)."""

    skill_id: str
    title: str
    description: str = ""
    instruction_file: str = ""
    mcp_servers: list[McpServerSpec] = field(default_factory=list)
    tool_include: list[str] = field(default_factory=list)
    local_tools: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoadedSkill:
    """Loaded skill: specification + instruction content."""

    spec: SkillSpec
    instruction_md: str
