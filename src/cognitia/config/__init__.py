"""Config - generic configuration loaders (YAML loaders, typed configs).

This module provides domain-agnostic loaders for:
- role -> skills mapping (RoleSkillsLoader, implements the RoleSkillsProvider Protocol)
- role router configuration (RoleRouterConfig, load_role_router_config)
"""

from cognitia.config.role_router import RoleRouterConfig, load_role_router_config
from cognitia.config.role_skills import YamlRoleSkillsLoader

__all__ = [
    "RoleRouterConfig",
    "YamlRoleSkillsLoader",
    "load_role_router_config",
]
