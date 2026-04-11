"""Skills module - SkillRegistry + types.

YamlSkillLoader has been moved to the application's infrastructure layer.
This module contains only the pure registry without IO.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.skills.registry import SkillRegistry
from swarmline.skills.types import LoadedSkill, McpServerSpec, SkillSpec

__all__ = [
    "LoadedSkill",
    "McpServerSpec",
    "SkillRegistry",
    "SkillSpec",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "YamlSkillLoader": (
        "swarmline.skills.loader",
        "YamlSkillLoader",
        "Install PyYAML to use YamlSkillLoader.",
    ),
    "load_mcp_from_settings": (
        "swarmline.skills.loader",
        "load_mcp_from_settings",
        "Install PyYAML to use load_mcp_from_settings.",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
