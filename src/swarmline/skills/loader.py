"""YamlSkillLoader - load skills from skill.yaml or SKILL.md files.

Supports two formats:
1. Swarmline native: skill.yaml + INSTRUCTION.md (two files)
2. Claude Code compatible: SKILL.md with YAML frontmatter (one file)

When both exist, skill.yaml takes priority.

§4.3: If MCP servers are already defined in .claude/settings.json,
SkillLoader normalizes them and augments them with skill settings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog
import yaml

from swarmline.skills.types import LoadedSkill, McpServerSpec, SkillSpec

_log = structlog.get_logger(component="skill_loader")

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def load_mcp_from_settings(project_root: Path) -> dict[str, McpServerSpec]:
    """Load MCP servers from .claude/settings.json (§4.3, R-401).

    Searches for mcpServers in project-level and user-level settings.
    """
    servers: dict[str, McpServerSpec] = {}

    # Priority: project -> user (project overrides)
    paths = [
        Path.home() / ".claude" / "settings.json",
        project_root / ".claude" / "settings.json",
        project_root / ".claude" / "settings.local.json",
    ]

    for settings_path in paths:
        if not settings_path.exists():
            continue
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            mcp_section = data.get("mcpServers", {})
            for name, cfg in mcp_section.items():
                transport = cfg.get("type", "url")
                servers[name] = McpServerSpec(
                    name=name,
                    transport=transport,
                    url=cfg.get("url"),
                    command=cfg.get("command"),
                    args=cfg.get("args"),
                    env=cfg.get("env"),
                    allow_private_network=cfg.get("allow_private_network", False),
                    allow_insecure_http=cfg.get("allow_insecure_http", False),
                )
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("settings_parse_error", path=str(settings_path), error=str(exc))
            continue

    return servers


def _parse_mcp_servers(raw_servers: list[dict]) -> list[McpServerSpec]:
    """Parse MCP server specs from a list of dicts."""
    result: list[McpServerSpec] = []
    for srv in raw_servers:
        result.append(
            McpServerSpec(
                name=srv.get("id", srv.get("name", "")),
                transport=srv.get("transport", "url"),
                url=srv.get("url"),
                command=srv.get("command"),
                args=srv.get("args"),
                env=srv.get("env"),
                allow_private_network=srv.get("allow_private_network", False),
                allow_insecure_http=srv.get("allow_insecure_http", False),
            )
        )
    return result


class YamlSkillLoader:
    """Loads skills from the skills/ directory.

    Supports two formats per subdirectory:
    1. skill.yaml + INSTRUCTION.md  (Swarmline native, higher priority)
    2. SKILL.md with YAML frontmatter (Claude Code compatible)

    §4.3: when .claude/settings.json is present, normalizes MCP servers
    and augments them with skill settings (skill config has priority §2.1).
    """

    def __init__(
        self,
        skills_dir: str | Path,
        project_root: str | Path | None = None,
    ) -> None:
        self._dir = Path(skills_dir)
        self._project_root = Path(project_root) if project_root else self._dir.parent
        self._settings_mcp: dict[str, McpServerSpec] = {}

    def load_all(self) -> list[LoadedSkill]:
        """Load all skills from subdirectories under skills/.

        For each subdirectory:
        - If skill.yaml exists → load Swarmline native format
        - Else if SKILL.md exists → load Claude Code format
        - Else → skip

        §4.3: also loads MCP from .claude/settings.json,
        skill config augments/overrides it (§2.1 priority).
        """
        self._settings_mcp = load_mcp_from_settings(self._project_root)

        skills: list[LoadedSkill] = []
        if not self._dir.exists():
            return skills

        for skill_dir in sorted(self._dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            # Security: prevent symlink-based directory traversal
            if not skill_dir.resolve().is_relative_to(self._project_root.resolve()):
                _log.warning(
                    "skill_dir_symlink_traversal",
                    path=str(skill_dir),
                    resolved=str(skill_dir.resolve()),
                )
                continue

            yaml_file = skill_dir / "skill.yaml"
            skill_md_file = skill_dir / "SKILL.md"

            if yaml_file.exists():
                skill = self._load_from_yaml(skill_dir, yaml_file)
            elif skill_md_file.exists():
                skill = self._load_from_skill_md(skill_dir, skill_md_file)
            else:
                continue

            if skill:
                skills.append(skill)

        return skills

    @property
    def settings_mcp_servers(self) -> dict[str, McpServerSpec]:
        """MCP servers loaded from .claude/settings.json."""
        return self._settings_mcp

    def _resolve_project_file(self, path: Path, *, event: str) -> Path | None:
        """Resolve an existing file under project_root and reject symlinks."""
        try:
            if path.is_symlink():
                _log.warning(event, path=str(path), reason="symlink")
                return None
            resolved = path.resolve(strict=True)
        except OSError as exc:
            _log.warning(event, path=str(path), reason=str(exc))
            return None

        if not resolved.is_relative_to(self._project_root.resolve()):
            _log.warning(
                event,
                path=str(path),
                resolved=str(resolved),
                project_root=str(self._project_root),
                reason="outside_project_root",
            )
            return None
        return resolved

    def _load_from_yaml(self, skill_dir: Path, yaml_file: Path) -> LoadedSkill | None:
        """Load a skill from Swarmline native format (skill.yaml + INSTRUCTION.md)."""
        yaml_path = self._resolve_project_file(yaml_file, event="skill_yaml_unsafe")
        if yaml_path is None:
            return None

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            _log.warning("skill_yaml_empty", path=str(yaml_file))
            return None

        skill_id = data.get("id", skill_dir.name)
        title = data.get("title", skill_id)
        description = data.get("description", "")

        # Parse MCP servers
        mcp_section = data.get("mcp", {})
        mcp_servers = _parse_mcp_servers(mcp_section.get("servers", []))

        # Tool include list
        tools_section = data.get("tools", {})
        tool_include = tools_section.get("include", [])

        # Local tools
        local_tools = data.get("local_tools", [])

        # Intents (for role routing)
        when_section = data.get("when", {})
        intents = when_section.get("intents", [])

        # Instruction file resolution:
        # 1. Explicit path in YAML → resolve relative to project_root
        # 2. Default → skill_dir / INSTRUCTION.md
        instruction_file_raw = data.get("instruction")
        if instruction_file_raw:
            instruction_path = (self._project_root / instruction_file_raw).resolve()
        else:
            instruction_path = skill_dir / "INSTRUCTION.md"

        # Security: prevent path traversal outside project_root
        if not instruction_path.resolve().is_relative_to(self._project_root.resolve()):
            _log.warning(
                "skill_instruction_path_traversal",
                skill_id=skill_id,
                path=str(instruction_path),
                project_root=str(self._project_root),
            )
            instruction_path = skill_dir / "INSTRUCTION.md"

        instruction_md = ""
        if instruction_path.exists():
            safe_instruction_path = self._resolve_project_file(
                instruction_path,
                event="skill_instruction_unsafe",
            )
            if safe_instruction_path is not None:
                instruction_md = safe_instruction_path.read_text(encoding="utf-8")
        else:
            _log.info(
                "skill_no_instruction",
                skill_id=skill_id,
                expected_path=str(instruction_path),
            )

        try:
            instruction_file = str(instruction_path.relative_to(self._project_root))
        except ValueError:
            instruction_file = instruction_path.name

        spec = SkillSpec(
            skill_id=skill_id,
            title=title,
            description=description,
            instruction_file=instruction_file,
            mcp_servers=mcp_servers,
            tool_include=tool_include,
            local_tools=local_tools,
            intents=intents,
        )
        _log.info("skill_loaded", skill_id=skill_id, source="yaml")
        return LoadedSkill(spec=spec, instruction_md=instruction_md)

    def _load_from_skill_md(
        self, skill_dir: Path, skill_md_file: Path
    ) -> LoadedSkill | None:
        """Load a skill from Claude Code compatible format (SKILL.md).

        SKILL.md format:
            ---
            name: my-skill
            description: "Short description"
            allowed-tools: [Bash, Read, Write]
            mcp-servers:            # Swarmline extension
              - name: server-name
                transport: url
                url: "https://..."
            intents: [keyword1]     # Swarmline extension
            ---

            # Markdown body = instruction_md
        """
        safe_skill_md = self._resolve_project_file(skill_md_file, event="skill_md_unsafe")
        if safe_skill_md is None:
            return None

        raw = safe_skill_md.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(raw)
        if not match:
            _log.warning(
                "skill_md_no_frontmatter",
                path=str(skill_md_file),
            )
            return None

        frontmatter_str, body = match.group(1), match.group(2)

        try:
            data = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError:
            _log.warning(
                "skill_md_invalid_frontmatter",
                path=str(skill_md_file),
            )
            return None

        if not data or not isinstance(data, dict):
            _log.warning("skill_md_empty_frontmatter", path=str(skill_md_file))
            return None

        skill_id = data.get("name", skill_dir.name)
        description = data.get("description", "")
        title = data.get("title", skill_id)

        # allowed-tools → tool_include (Claude Code field name)
        tool_include = data.get("allowed-tools", [])

        # Swarmline extensions (not in standard Claude Code format)
        mcp_servers = _parse_mcp_servers(data.get("mcp-servers", []))
        intents = data.get("intents", [])
        local_tools = data.get("local-tools", [])

        instruction_md = body.strip()

        spec = SkillSpec(
            skill_id=skill_id,
            title=title,
            description=description,
            instruction_file="SKILL.md",
            mcp_servers=mcp_servers,
            tool_include=tool_include,
            local_tools=local_tools,
            intents=intents,
        )
        _log.info("skill_loaded", skill_id=skill_id, source="skill_md")
        return LoadedSkill(spec=spec, instruction_md=instruction_md)


# SkillRegistry lives in skills/registry.py (SRP)
