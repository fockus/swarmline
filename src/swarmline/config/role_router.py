"""YAML loader for KeywordRoleRouter configuration.

Returns the typed RoleRouterConfig dataclass instead of a raw dict.
Accepts yaml_path via DI - not tied to a specific project structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RoleRouterConfig:
    """Typed configuration for KeywordRoleRouter.

    Attributes:
        default_role: Default role (if no keyword matched).
        keywords: Mapping role_id -> list of keywords for automatic switching.
    """

    default_role: str = "default"
    keywords: dict[str, list[str]] = field(default_factory=dict)


def load_role_router_config(yaml_path: Path) -> RoleRouterConfig:
    """Load router configuration from YAML.

    Args:
        yaml_path: Path to the role_router.yaml file.

    Returns:
        RoleRouterConfig with default_role and keywords.
    """
    if not yaml_path.exists():
        return RoleRouterConfig()

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return RoleRouterConfig(
        default_role=data.get("default_role", "default"),
        keywords=data.get("keywords", {}),
    )
