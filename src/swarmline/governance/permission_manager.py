"""PermissionManager — hierarchical permission checking with named profiles.

5 built-in profiles (read-only → deploy-capable).
Permission hierarchy: each level inherits all lower-level capabilities.
Actions checked against profile level, tool allowlist, and denied patterns.
"""

from __future__ import annotations

import fnmatch

from swarmline.governance.types import PermissionLevel, PermissionProfile

_READ_TOOLS = frozenset(
    {
        "read_file",
        "list_files",
        "search_files",
        "grep",
    }
)

_EDIT_TOOLS = _READ_TOOLS | frozenset(
    {
        "write_file",
        "edit_file",
        "create_file",
    }
)

_GIT_TOOLS = _EDIT_TOOLS | frozenset(
    {
        "git_commit",
        "git_push",
        "git_branch",
        "git_checkout",
    }
)

_NETWORK_TOOLS = _GIT_TOOLS | frozenset(
    {
        "http_request",
        "web_search",
        "api_call",
    }
)

_DEPLOY_TOOLS = _NETWORK_TOOLS | frozenset(
    {
        "deploy_tool",
        "deploy_staging",
        "deploy_production",
    }
)

_ACTION_LEVEL_MAP: dict[str, PermissionLevel] = {
    "read_*": PermissionLevel.READ_ONLY,
    "list_*": PermissionLevel.READ_ONLY,
    "search_*": PermissionLevel.READ_ONLY,
    "grep*": PermissionLevel.READ_ONLY,
    "write_*": PermissionLevel.EDIT,
    "edit_*": PermissionLevel.EDIT,
    "create_*": PermissionLevel.EDIT,
    "git_*": PermissionLevel.GIT_WRITE,
    "force_*": PermissionLevel.GIT_WRITE,
    "http_*": PermissionLevel.NETWORK_ENABLED,
    "web_*": PermissionLevel.NETWORK_ENABLED,
    "api_*": PermissionLevel.NETWORK_ENABLED,
    "deploy*": PermissionLevel.DEPLOY_CAPABLE,
    "delete_*": PermissionLevel.EDIT,
}

_BUILTIN_PROFILES: tuple[PermissionProfile, ...] = (
    PermissionProfile(
        name="read-only",
        level=PermissionLevel.READ_ONLY,
        allowed_tools=_READ_TOOLS,
        denied_patterns=(
            "write_*",
            "edit_*",
            "create_*",
            "delete_*",
            "git_*",
            "force_*",
            "deploy*",
            "http_*",
            "web_*",
            "api_*",
        ),
    ),
    PermissionProfile(
        name="editor",
        level=PermissionLevel.EDIT,
        allowed_tools=_EDIT_TOOLS,
        denied_patterns=("git_*", "force_*", "deploy*", "http_*", "web_*", "api_*"),
    ),
    PermissionProfile(
        name="git-writer",
        level=PermissionLevel.GIT_WRITE,
        allowed_tools=_GIT_TOOLS,
        denied_patterns=("deploy*", "http_*", "web_*", "api_*"),
    ),
    PermissionProfile(
        name="network-enabled",
        level=PermissionLevel.NETWORK_ENABLED,
        allowed_tools=_NETWORK_TOOLS,
        denied_patterns=("deploy*",),
    ),
    PermissionProfile(
        name="deploy-capable",
        level=PermissionLevel.DEPLOY_CAPABLE,
        allowed_tools=_DEPLOY_TOOLS,
        denied_patterns=(),
    ),
)


class PermissionManager:
    """Hierarchical permission manager with named profiles.

    Implements PermissionManagerPort:
    - check_permission: verify action allowed by profile level + tool allowlist
    - get_profile: lookup profile by name
    - list_profiles: return all registered profiles
    """

    def __init__(self, profiles: tuple[PermissionProfile, ...] | None = None) -> None:
        profs = profiles if profiles is not None else _BUILTIN_PROFILES
        self._profiles: dict[str, PermissionProfile] = {p.name: p for p in profs}

    def check_permission(
        self, profile_name: str, action: str, tool_name: str | None = None
    ) -> bool:
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        if tool_name is not None and tool_name not in profile.allowed_tools:
            return False
        for pattern in profile.denied_patterns:
            if fnmatch.fnmatch(action, pattern):
                return False
        required_level = self._action_required_level(action)
        return profile.level >= required_level

    def get_profile(self, name: str) -> PermissionProfile | None:
        return self._profiles.get(name)

    def list_profiles(self) -> list[PermissionProfile]:
        return list(self._profiles.values())

    @staticmethod
    def _action_required_level(action: str) -> PermissionLevel:
        for pattern, level in _ACTION_LEVEL_MAP.items():
            if fnmatch.fnmatch(action, pattern):
                return level
        return PermissionLevel.DEPLOY_CAPABLE
