"""YamlRoleSkillsLoader - load role -> skills mappings from YAML.

Implements the RoleSkillsProvider Protocol (ISP: get_skills, get_local_tools).
Accepts yaml_path via DI - not tied to a specific project structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class YamlRoleSkillsLoader:
    """Loader for role_id -> skills mappings from role_skills.yaml.

    Implements the RoleSkillsProvider Protocol.

    Args:
        yaml_path: Path to the YAML file containing the role mapping.
    """

    def __init__(self, yaml_path: Path) -> None:
        self._path = yaml_path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load the YAML file."""
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def get_skills(self, role_id: str) -> list[str]:
        """Get the list of skill_ids for a role."""
        role_data = self._data.get(role_id, {})
        result: list[str] = role_data.get("skills", [])
        return result

    def get_local_tools(self, role_id: str) -> list[str]:
        """Get the list of local tools for a role."""
        role_data = self._data.get(role_id, {})
        result: list[str] = role_data.get("local_tools", [])
        return result

    def list_roles(self) -> list[str]:
        """List all available roles."""
        return list(self._data.keys())
