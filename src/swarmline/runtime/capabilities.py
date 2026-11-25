"""Capability descriptors for runtime tiers and capability negotiation.

Capability model v2 (generated matrix: docs/runtimes.md):

- Every capability dimension has a support level: ``"native"`` (provided by
  the underlying runtime/SDK), ``"emulated"`` (provided by the Swarmline
  portable layer), or ``"none"``.
- Requirements accept an optional minimum level: ``"mcp"`` means at least
  emulated, ``"mcp:native"`` means native only.
- Legacy boolean flags (``supports_mcp=...``) and legacy requirement names
  (``native_subagents``, ``builtin_todo``, ...) keep working through aliases.
- Conditional capabilities (e.g. deepagents native built-ins) are narrowed by
  :meth:`RuntimeCapabilities.resolve` against a concrete configuration.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Literal, cast

VALID_RUNTIME_NAMES = frozenset(
    {
        "claude_sdk",
        "deepagents",
        "thin",
        "cli",
        "openai_agents",
        "pi_sdk",
        "headless",
        "temporal",
    }
)
RUNTIME_TIERS = frozenset({"full", "light"})
VALID_FEATURE_MODES = frozenset({"portable", "hybrid", "native_first"})

RuntimeTier = Literal["full", "light"]
FeatureMode = Literal["portable", "hybrid", "native_first"]
CapabilitySupport = Literal["native", "emulated", "none"]

VALID_SUPPORT_LEVELS = frozenset({"native", "emulated", "none"})
_SUPPORT_ORDER: dict[str, int] = {"none": 0, "emulated": 1, "native": 2}

#: Capability dimensions of the v2 model. Every dimension carries a support
#: level (native/emulated/none) instead of a boolean.
CAPABILITY_DIMENSIONS: tuple[str, ...] = (
    "mcp",
    "resume",
    "interrupt",
    "permissions",
    "hitl",
    "user_input",
    "subagents",
    "memory",
    "todo",
    "compaction",
    "project_instructions",
    "provider_override",
    "structured_output",
    "thinking_stream",
    "usage_reporting",
    "cost_tracking",
    "builtin_tools",
    "web_tools",
)

#: Legacy v1 requirement flag -> (dimension, minimum level).
_LEGACY_FLAG_ALIASES: dict[str, tuple[str, str]] = {
    "native_permissions": ("permissions", "native"),
    "native_subagents": ("subagents", "native"),
    "builtin_memory": ("memory", "native"),
    "builtin_todo": ("todo", "native"),
    "builtin_compaction": ("compaction", "native"),
}

#: Legacy v1 constructor kwarg -> (dimension, level implied by True).
_LEGACY_KWARG_ALIASES: dict[str, tuple[str, str]] = {
    "supports_mcp": ("mcp", "native"),
    "supports_resume": ("resume", "native"),
    "supports_interrupt": ("interrupt", "native"),
    "supports_native_permissions": ("permissions", "native"),
    "supports_user_input": ("user_input", "native"),
    "supports_native_subagents": ("subagents", "native"),
    "supports_builtin_memory": ("memory", "native"),
    "supports_builtin_todo": ("todo", "native"),
    "supports_builtin_compaction": ("compaction", "native"),
    "supports_hitl": ("hitl", "native"),
    "supports_project_instructions": ("project_instructions", "native"),
    "supports_provider_override": ("provider_override", "native"),
}

#: All requirement flag names accepted by CapabilityRequirements
#: (dimensions + legacy aliases; an optional ":native"/":emulated" suffix
#: is validated separately).
RUNTIME_CAPABILITY_FLAGS = frozenset(CAPABILITY_DIMENSIONS) | frozenset(
    _LEGACY_FLAG_ALIASES
)


def parse_capability_flag(flag: str) -> tuple[str, str]:
    """Parse a requirement flag into ``(dimension, minimum_level)``.

    Accepts ``"mcp"`` (minimum: emulated), ``"mcp:native"``,
    ``"mcp:emulated"``, and legacy aliases like ``"native_subagents"``
    (which implies ``subagents:native``).
    """
    name, _, level = flag.partition(":")
    if name in _LEGACY_FLAG_ALIASES:
        dimension, implied_level = _LEGACY_FLAG_ALIASES[name]
        min_level = level or implied_level
    elif name in CAPABILITY_DIMENSIONS:
        dimension = name
        min_level = level or "emulated"
    else:
        raise ValueError(f"Unknown capability flags: {name}")

    if min_level not in ("native", "emulated"):
        raise ValueError(
            f"Unknown capability level in '{flag}'. Expected 'native' or 'emulated'."
        )
    return dimension, min_level


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
        unknown: list[str] = []
        for flag in normalized:
            try:
                parse_capability_flag(flag)
            except ValueError:
                unknown.append(flag)
        if unknown:
            raise ValueError(f"Unknown capability flags: {', '.join(sorted(unknown))}")

        object.__setattr__(self, "flags", normalized)

    @property
    def is_empty(self) -> bool:
        return self.tier is None and not self.flags


class RuntimeCapabilities:
    """Actual runtime capabilities guaranteed by swarmline.

    Each capability dimension holds a support level:

    - ``"native"``  — provided by the underlying runtime/SDK path;
    - ``"emulated"`` — provided by the Swarmline portable layer;
    - ``"none"``   — not available.

    Legacy boolean constructor kwargs (``supports_mcp=True``) are accepted
    with a :class:`DeprecationWarning` and map to ``native``/``none``.
    """

    def __init__(
        self,
        runtime_name: str,
        tier: RuntimeTier,
        *,
        mcp: CapabilitySupport = "none",
        resume: CapabilitySupport = "none",
        interrupt: CapabilitySupport = "none",
        permissions: CapabilitySupport = "none",
        hitl: CapabilitySupport = "none",
        user_input: CapabilitySupport = "none",
        subagents: CapabilitySupport = "none",
        memory: CapabilitySupport = "none",
        todo: CapabilitySupport = "none",
        compaction: CapabilitySupport = "none",
        project_instructions: CapabilitySupport = "none",
        provider_override: CapabilitySupport = "none",
        structured_output: CapabilitySupport = "none",
        thinking_stream: CapabilitySupport = "none",
        usage_reporting: CapabilitySupport = "none",
        cost_tracking: CapabilitySupport = "none",
        builtin_tools: CapabilitySupport = "none",
        web_tools: CapabilitySupport = "none",
        **legacy_flags: bool,
    ) -> None:
        if tier not in RUNTIME_TIERS:
            raise ValueError(
                f"Unknown runtime tier: '{tier}'. "
                f"Expected one of: {', '.join(sorted(RUNTIME_TIERS))}"
            )

        levels: dict[str, CapabilitySupport] = {
            "mcp": mcp,
            "resume": resume,
            "interrupt": interrupt,
            "permissions": permissions,
            "hitl": hitl,
            "user_input": user_input,
            "subagents": subagents,
            "memory": memory,
            "todo": todo,
            "compaction": compaction,
            "project_instructions": project_instructions,
            "provider_override": provider_override,
            "structured_output": structured_output,
            "thinking_stream": thinking_stream,
            "usage_reporting": usage_reporting,
            "cost_tracking": cost_tracking,
            "builtin_tools": builtin_tools,
            "web_tools": web_tools,
        }

        if legacy_flags:
            unknown = [k for k in legacy_flags if k not in _LEGACY_KWARG_ALIASES]
            if unknown:
                raise TypeError(
                    f"Unknown RuntimeCapabilities arguments: {', '.join(sorted(unknown))}"
                )
            warnings.warn(
                "Boolean 'supports_*' arguments to RuntimeCapabilities are "
                "deprecated; use capability levels instead "
                "(e.g. mcp='native').",
                DeprecationWarning,
                stacklevel=2,
            )
            for kwarg, value in legacy_flags.items():
                dimension, native_level = _LEGACY_KWARG_ALIASES[kwarg]
                levels[dimension] = cast(
                    CapabilitySupport, native_level if value else "none"
                )

        for dimension, level in levels.items():
            if level not in VALID_SUPPORT_LEVELS:
                raise ValueError(
                    f"Unknown support level '{level}' for capability "
                    f"'{dimension}'. Expected one of: native, emulated, none"
                )

        self.runtime_name = runtime_name
        self.tier: RuntimeTier = tier
        self._levels: dict[str, CapabilitySupport] = levels

    # -- dimension accessors -------------------------------------------------

    def level(self, dimension: str) -> CapabilitySupport:
        """Support level for a capability dimension."""
        if dimension not in self._levels:
            raise ValueError(f"Unknown capability dimension: '{dimension}'")
        return self._levels[dimension]

    def levels(self) -> dict[str, CapabilitySupport]:
        """Copy of the full dimension -> level mapping."""
        return dict(self._levels)

    def __getattr__(self, name: str) -> Any:
        levels = self.__dict__.get("_levels")
        if levels is not None and name in levels:
            return levels[name]
        raise AttributeError(name)

    def replace(self, **level_overrides: CapabilitySupport) -> RuntimeCapabilities:
        """New descriptor with some dimension levels replaced."""
        levels = dict(self._levels)
        for dimension, level in level_overrides.items():
            if dimension not in levels:
                raise ValueError(f"Unknown capability dimension: '{dimension}'")
            if level not in VALID_SUPPORT_LEVELS:
                raise ValueError(
                    f"Unknown support level '{level}' for capability '{dimension}'. "
                    "Expected one of: native, emulated, none"
                )
            levels[dimension] = level
        clone = RuntimeCapabilities.__new__(RuntimeCapabilities)
        clone.runtime_name = self.runtime_name
        clone.tier = self.tier
        clone._levels = levels
        return clone

    # -- legacy boolean surface (deprecated reads, kept for one minor) -------

    @property
    def supports_mcp(self) -> bool:
        return self._levels["mcp"] != "none"

    @property
    def supports_resume(self) -> bool:
        return self._levels["resume"] != "none"

    @property
    def supports_interrupt(self) -> bool:
        return self._levels["interrupt"] != "none"

    @property
    def supports_native_permissions(self) -> bool:
        return self._levels["permissions"] == "native"

    @property
    def supports_user_input(self) -> bool:
        return self._levels["user_input"] != "none"

    @property
    def supports_native_subagents(self) -> bool:
        return self._levels["subagents"] == "native"

    @property
    def supports_builtin_memory(self) -> bool:
        return self._levels["memory"] == "native"

    @property
    def supports_builtin_todo(self) -> bool:
        return self._levels["todo"] == "native"

    @property
    def supports_builtin_compaction(self) -> bool:
        return self._levels["compaction"] == "native"

    @property
    def supports_hitl(self) -> bool:
        return self._levels["hitl"] != "none"

    @property
    def supports_project_instructions(self) -> bool:
        return self._levels["project_instructions"] != "none"

    @property
    def supports_provider_override(self) -> bool:
        return self._levels["provider_override"] != "none"

    # -- negotiation ----------------------------------------------------------

    def enabled_flags(self) -> frozenset[str]:
        """Capability dimensions supported at least at the emulated level."""
        enabled = {
            dimension for dimension, level in self._levels.items() if level != "none"
        }
        for legacy_flag, (dimension, min_level) in _LEGACY_FLAG_ALIASES.items():
            if _SUPPORT_ORDER[self._levels[dimension]] >= _SUPPORT_ORDER[min_level]:
                enabled.add(legacy_flag)
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

        for flag in requirements.flags:
            dimension, min_level = parse_capability_flag(flag)
            actual = self._levels[dimension]
            if _SUPPORT_ORDER[actual] < _SUPPORT_ORDER[min_level]:
                missing.append(flag)

        return tuple(missing)

    def resolve(self, config: Any | None) -> RuntimeCapabilities:
        """Narrow conditional capabilities against a concrete configuration.

        The static table describes the runtime's potential; some capabilities
        only hold for specific configurations (e.g. deepagents native
        built-ins require native mode). ``config`` is duck-typed:
        ``RuntimeConfig`` and ``AgentConfig`` both work.
        """
        if config is None:
            return self
        resolver = _CONDITIONAL_RESOLVERS.get(self.runtime_name)
        if resolver is None:
            return self
        return resolver(self, config)

    # -- dunder ---------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuntimeCapabilities):
            return NotImplemented
        return (
            self.runtime_name == other.runtime_name
            and self.tier == other.tier
            and self._levels == other._levels
        )

    def __repr__(self) -> str:
        non_none = ", ".join(
            f"{dimension}={level}"
            for dimension, level in self._levels.items()
            if level != "none"
        )
        return (
            f"RuntimeCapabilities(runtime_name={self.runtime_name!r}, "
            f"tier={self.tier!r}, {non_none})"
        )


# ---------------------------------------------------------------------------
# Conditional resolvers (potential -> actual for a given config)
# ---------------------------------------------------------------------------


def _config_is_native_mode(config: Any) -> bool:
    if getattr(config, "allow_native_features", False):
        return True
    return getattr(config, "feature_mode", "portable") in {"hybrid", "native_first"}


def _resolve_deepagents(caps: RuntimeCapabilities, config: Any) -> RuntimeCapabilities:
    """deepagents: native built-ins/HITL/subagents/resume need native mode."""
    if _config_is_native_mode(config):
        native_config = getattr(config, "native_config", None) or {}
        if caps.level("resume") != "none" and not native_config.get("checkpointer"):
            return caps.replace(resume="none")
        return caps
    return caps.replace(
        resume="none",
        hitl="none",
        user_input="none",
        subagents="none",
        memory="none",
        todo="none",
        compaction="none",
        builtin_tools="none",
    )


def _thin_provider_slug(config: Any) -> str | None:
    model = getattr(config, "model", None)
    if not model:
        return None
    try:
        from swarmline.runtime.provider_resolver import resolve_provider

        return resolve_provider(
            model, base_url=getattr(config, "base_url", None)
        ).provider
    except Exception:
        return None


def _resolve_thin(caps: RuntimeCapabilities, config: Any) -> RuntimeCapabilities:
    """thin: structured output / thinking depend on the selected provider."""
    provider = _thin_provider_slug(config)
    if provider is None:
        return caps

    overrides: dict[str, CapabilitySupport] = {}
    if caps.level("structured_output") != "none":
        if provider in {"openai", "openrouter"}:
            overrides["structured_output"] = "native"
    if caps.level("thinking_stream") != "none" and provider != "anthropic":
        overrides["thinking_stream"] = "none"
    return caps.replace(**overrides) if overrides else caps


def _resolve_claude_sdk(caps: RuntimeCapabilities, config: Any) -> RuntimeCapabilities:
    """claude_sdk: neither can_use_tool nor tool_policy is consulted under
    permission_mode="bypassPermissions", so permissions resolve to none there
    regardless of what enforcement sources the config carries."""
    mode = getattr(config, "permission_mode", None)
    if mode == "bypassPermissions":
        return caps.replace(permissions="none")
    return caps


_CONDITIONAL_RESOLVERS: dict[str, Any] = {
    "claude_sdk": _resolve_claude_sdk,
    "deepagents": _resolve_deepagents,
    "thin": _resolve_thin,
}


# ---------------------------------------------------------------------------
# Built-in capability matrix
#
# Values reflect what the CURRENT code actually delivers on the Agent
# production path (runtime consistency audit, 2026-07-03).
# A level is only raised in the same change that implements the feature.
# ---------------------------------------------------------------------------

_CAPABILITIES_BY_RUNTIME: dict[str, RuntimeCapabilities] = {
    "claude_sdk": RuntimeCapabilities(
        "claude_sdk",
        "full",
        mcp="native",
        resume="native",
        interrupt="native",
        permissions="native",
        subagents="native",
        todo="native",
        compaction="native",
        project_instructions="native",
        structured_output="native",
        thinking_stream="native",
        usage_reporting="native",
        cost_tracking="native",
        builtin_tools="native",
        web_tools="native",
    ),
    "deepagents": RuntimeCapabilities(
        "deepagents",
        "full",
        mcp="emulated",
        resume="native",
        interrupt="emulated",
        hitl="native",
        user_input="native",
        subagents="native",
        memory="native",
        todo="native",
        compaction="native",
        project_instructions="emulated",
        provider_override="native",
        structured_output="emulated",
        usage_reporting="native",
        builtin_tools="native",
    ),
    "thin": RuntimeCapabilities(
        "thin",
        "light",
        mcp="emulated",
        interrupt="emulated",
        permissions="emulated",
        subagents="emulated",
        todo="emulated",
        compaction="emulated",
        project_instructions="emulated",
        provider_override="native",
        structured_output="emulated",
        thinking_stream="emulated",
        usage_reporting="native",
        cost_tracking="emulated",
        builtin_tools="emulated",
    ),
    "cli": RuntimeCapabilities(
        "cli",
        "light",
        interrupt="emulated",
        structured_output="emulated",
    ),
    "openai_agents": RuntimeCapabilities(
        "openai_agents",
        "full",
        mcp="native",
        interrupt="emulated",
        project_instructions="emulated",
        provider_override="native",
        structured_output="native",
        thinking_stream="native",
        usage_reporting="native",
    ),
    "pi_sdk": RuntimeCapabilities(
        "pi_sdk",
        "full",
        resume="native",
        interrupt="native",
        project_instructions="native",
        provider_override="native",
        structured_output="emulated",
        thinking_stream="native",
        usage_reporting="native",
        cost_tracking="native",
        builtin_tools="native",
    ),
    "headless": RuntimeCapabilities(
        "headless",
        "light",
    ),
    "temporal": RuntimeCapabilities(
        "temporal",
        "full",
        mcp="native",
        resume="native",
        interrupt="native",
        hitl="native",
        provider_override="native",
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
