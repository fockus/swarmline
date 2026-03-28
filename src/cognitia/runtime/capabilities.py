"""Capability descriptors for runtime tiers and capability negotiation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VALID_RUNTIME_NAMES = frozenset({"claude_sdk", "deepagents", "thin", "cli", "openai_agents"})
RUNTIME_TIERS = frozenset({"full", "light"})
VALID_FEATURE_MODES = frozenset({"portable", "hybrid", "native_first"})
RUNTIME_CAPABILITY_FLAGS = frozenset(
    {
        "mcp",
        "resume",
        "interrupt",
        "native_permissions",
        "user_input",
        "native_subagents",
        "builtin_memory",
        "builtin_todo",
        "builtin_compaction",
        "hitl",
        "project_instructions",
        "provider_override",
    }
)

RuntimeTier = Literal["full", "light"]
FeatureMode = Literal["portable", "hybrid", "native_first"]


@dataclass(frozen=True)
class CapabilityRequirements:
    """Application requirements for runtime capabilities."""

    tier: RuntimeTier | None = None
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tier is not None and self.tier not in RUNTIME_TIERS:
            raise ValueError(
                f"Unknown runtime tier: '{self.tier}'. "
                f"Expected one of: {', '.join(sorted(RUNTIME_TIERS))}"
            )

        normalized = tuple(dict.fromkeys(self.flags))
        unknown = [flag for flag in normalized if flag not in RUNTIME_CAPABILITY_FLAGS]
        if unknown:
            raise ValueError(f"Unknown capability flags: {', '.join(sorted(unknown))}")

        object.__setattr__(self, "flags", normalized)

    @property
    def is_empty(self) -> bool:
        return self.tier is None and not self.flags


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Actual runtime capabilities guaranteed by cognitia."""

    runtime_name: str
    tier: RuntimeTier
    supports_mcp: bool = False
    supports_resume: bool = False
    supports_interrupt: bool = False
    supports_native_permissions: bool = False
    supports_user_input: bool = False
    supports_native_subagents: bool = False
    supports_builtin_memory: bool = False
    supports_builtin_todo: bool = False
    supports_hitl: bool = False
    supports_builtin_compaction: bool = False
    supports_project_instructions: bool = False
    supports_provider_override: bool = False

    def enabled_flags(self) -> frozenset[str]:
        """Capability flag names supported by the runtime."""
        enabled = {flag for flag, is_enabled in self._flag_map().items() if is_enabled}
        return frozenset(enabled)

    def supports(self, requirements: CapabilityRequirements | None) -> bool:
        """Check whether the runtime satisfies the requirements."""
        return not self.missing(requirements)

    def missing(self, requirements: CapabilityRequirements | None) -> tuple[str, ...]:
        """Return the list of missing capability flags."""
        if requirements is None or requirements.is_empty:
            return ()

        missing: list[str] = []
        if requirements.tier and self.tier != requirements.tier:
            missing.append(f"tier:{requirements.tier}")

        enabled = self.enabled_flags()
        for flag in requirements.flags:
            if flag not in enabled:
                missing.append(flag)

        return tuple(missing)

    def _flag_map(self) -> dict[str, bool]:
        return {
            "mcp": self.supports_mcp,
            "resume": self.supports_resume,
            "interrupt": self.supports_interrupt,
            "native_permissions": self.supports_native_permissions,
            "user_input": self.supports_user_input,
            "native_subagents": self.supports_native_subagents,
            "builtin_memory": self.supports_builtin_memory,
            "builtin_todo": self.supports_builtin_todo,
            "builtin_compaction": self.supports_builtin_compaction,
            "hitl": self.supports_hitl,
            "project_instructions": self.supports_project_instructions,
            "provider_override": self.supports_provider_override,
        }


_CAPABILITIES_BY_RUNTIME: dict[str, RuntimeCapabilities] = {
    "claude_sdk": RuntimeCapabilities(
        runtime_name="claude_sdk",
        tier="full",
        supports_mcp=True,
        supports_resume=True,
        supports_interrupt=True,
    ),
    "deepagents": RuntimeCapabilities(
        runtime_name="deepagents",
        tier="full",
        supports_resume=True,
        supports_native_subagents=True,
        supports_builtin_todo=True,
        supports_provider_override=True,
    ),
    "thin": RuntimeCapabilities(
        runtime_name="thin",
        tier="light",
        supports_mcp=True,
        supports_provider_override=True,
    ),
    "cli": RuntimeCapabilities(
        runtime_name="cli",
        tier="light",
    ),
    "openai_agents": RuntimeCapabilities(
        runtime_name="openai_agents",
        tier="full",
        supports_mcp=True,
        supports_provider_override=True,
    ),
}


def get_runtime_capabilities(runtime_name: str) -> RuntimeCapabilities:
    """Get the capability descriptor for a runtime."""
    if runtime_name not in VALID_RUNTIME_NAMES:
        raise ValueError(
            f"Unknown runtime: '{runtime_name}'. "
            f"Expected one of: {', '.join(sorted(VALID_RUNTIME_NAMES))}"
        )
    return _CAPABILITIES_BY_RUNTIME[runtime_name]
