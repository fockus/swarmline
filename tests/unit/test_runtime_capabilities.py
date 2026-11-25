"""Unit: runtime capability descriptors and requirements (model v2)."""

from __future__ import annotations

import pytest
from swarmline.runtime.capabilities import (
    CAPABILITY_DIMENSIONS,
    CapabilityRequirements,
    RuntimeCapabilities,
    get_runtime_capabilities,
    parse_capability_flag,
)
from swarmline.runtime.types import RuntimeConfig


class TestCapabilityRequirements:
    """CapabilityRequirements - validation and comparison."""

    def test_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="tier"):
            CapabilityRequirements(tier="unknown")  # type: ignore[arg-type]

    def test_invalid_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown capability flags"):
            CapabilityRequirements(flags=("unknown_flag",))

    def test_invalid_level_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown capability flags"):
            CapabilityRequirements(flags=("mcp:super",))

    def test_level_suffix_accepted(self) -> None:
        req = CapabilityRequirements(flags=("mcp:native", "resume:emulated"))
        assert req.flags == ("mcp:native", "resume:emulated")

    def test_legacy_alias_accepted(self) -> None:
        req = CapabilityRequirements(flags=("native_subagents", "builtin_todo"))
        assert req.flags == ("native_subagents", "builtin_todo")


class TestParseCapabilityFlag:
    def test_plain_flag_means_emulated_minimum(self) -> None:
        assert parse_capability_flag("mcp") == ("mcp", "emulated")

    def test_native_suffix(self) -> None:
        assert parse_capability_flag("mcp:native") == ("mcp", "native")

    def test_legacy_alias_implies_native(self) -> None:
        assert parse_capability_flag("native_subagents") == ("subagents", "native")
        assert parse_capability_flag("builtin_todo") == ("todo", "native")
        assert parse_capability_flag("builtin_memory") == ("memory", "native")
        assert parse_capability_flag("builtin_compaction") == ("compaction", "native")
        assert parse_capability_flag("native_permissions") == (
            "permissions",
            "native",
        )


class TestRuntimeCapabilities:
    """get_runtime_capabilities() — descriptor per runtime."""

    def test_claude_sdk_is_full_tier(self) -> None:
        caps = get_runtime_capabilities("claude_sdk")
        assert caps.runtime_name == "claude_sdk"
        assert caps.tier == "full"
        assert caps.level("mcp") == "native"
        assert caps.level("interrupt") == "native"
        assert caps.level("resume") == "native"
        assert caps.level("structured_output") == "native"
        assert caps.level("usage_reporting") == "native"
        # legacy boolean surface still works
        assert caps.supports_mcp is True
        assert caps.supports_interrupt is True
        assert caps.supports_resume is True

    def test_deepagents_potential_is_full_tier(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        assert caps.runtime_name == "deepagents"
        assert caps.tier == "full"
        # potential (unresolved) capabilities include native-mode features
        assert caps.level("resume") == "native"
        assert caps.level("hitl") == "native"
        assert caps.level("subagents") == "native"
        assert caps.level("todo") == "native"
        assert caps.level("mcp") == "emulated"
        assert caps.level("provider_override") == "native"

    def test_deepagents_portable_resolve_narrows_native_features(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        resolved = caps.resolve(RuntimeConfig(runtime_name="deepagents"))
        assert resolved.level("hitl") == "none"
        assert resolved.level("subagents") == "none"
        assert resolved.level("todo") == "none"
        assert resolved.level("resume") == "none"
        # unconditional capabilities survive
        assert resolved.level("mcp") == "emulated"
        assert resolved.level("provider_override") == "native"

    def test_deepagents_native_mode_resume_requires_checkpointer(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        without = caps.resolve(
            RuntimeConfig(runtime_name="deepagents", feature_mode="native_first")
        )
        assert without.level("resume") == "none"
        assert without.level("hitl") == "native"

        with_checkpointer = caps.resolve(
            RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
                native_config={"checkpointer": object()},
            )
        )
        assert with_checkpointer.level("resume") == "native"

    def test_thin_is_light_tier(self) -> None:
        caps = get_runtime_capabilities("thin")
        assert caps.runtime_name == "thin"
        assert caps.tier == "light"
        assert caps.level("provider_override") == "native"
        assert caps.level("mcp") == "emulated"
        assert caps.level("interrupt") == "emulated"
        assert caps.level("subagents") == "emulated"
        assert caps.supports_provider_override is True
        # emulated subagents are NOT native subagents
        assert caps.supports_native_subagents is False

    def test_pi_sdk_is_full_tier(self) -> None:
        caps = get_runtime_capabilities("pi_sdk")
        assert caps.runtime_name == "pi_sdk"
        assert caps.tier == "full"
        assert caps.level("interrupt") == "native"
        assert caps.level("provider_override") == "native"
        assert caps.level("thinking_stream") == "native"
        assert caps.level("project_instructions") == "native"

    def test_supports_returns_false_for_missing_requirements(self) -> None:
        caps = get_runtime_capabilities("thin")
        req = CapabilityRequirements(
            tier="full",
            flags=("hitl", "native_permissions"),
        )
        assert caps.supports(req) is False
        assert set(caps.missing(req)) == {
            "tier:full",
            "hitl",
            "native_permissions",
        }

    def test_supports_returns_true_for_supported_requirements(self) -> None:
        caps = get_runtime_capabilities("claude_sdk")
        req = CapabilityRequirements(flags=("mcp", "interrupt", "resume"))
        assert caps.supports(req) is True
        assert caps.missing(req) == ()

    def test_emulated_does_not_satisfy_native_requirement(self) -> None:
        caps = get_runtime_capabilities("thin")
        assert caps.supports(CapabilityRequirements(flags=("mcp",))) is True
        assert caps.supports(CapabilityRequirements(flags=("mcp:native",))) is False
        assert caps.missing(CapabilityRequirements(flags=("mcp:native",))) == (
            "mcp:native",
        )

    def test_every_dimension_has_a_level(self) -> None:
        for runtime in (
            "claude_sdk",
            "deepagents",
            "thin",
            "cli",
            "openai_agents",
            "pi_sdk",
            "headless",
        ):
            caps = get_runtime_capabilities(runtime)
            for dimension in CAPABILITY_DIMENSIONS:
                assert caps.level(dimension) in {"native", "emulated", "none"}

    def test_no_dead_capability_dimensions(self) -> None:
        """Every dimension must be delivered by at least one runtime.

        Guards against declaring requirable capabilities that no built-in
        runtime can ever satisfy (RUNTIME-PARITY-PLAN A3).
        """
        # web_tools lands with the portable web pack (plan D8)
        allowed_dead = {"web_tools"}
        dead: list[str] = []
        for dimension in CAPABILITY_DIMENSIONS:
            if any(
                get_runtime_capabilities(runtime).level(dimension) != "none"
                for runtime in (
                    "claude_sdk",
                    "deepagents",
                    "thin",
                    "cli",
                    "openai_agents",
                    "pi_sdk",
                )
            ):
                continue
            dead.append(dimension)
        assert set(dead) <= allowed_dead, f"Dead capability dimensions: {dead}"


class TestLegacyConstructor:
    def test_legacy_bool_kwargs_map_to_levels(self) -> None:
        with pytest.warns(DeprecationWarning):
            caps = RuntimeCapabilities(
                "custom",
                "light",
                supports_mcp=True,
                supports_provider_override=False,
            )
        assert caps.level("mcp") == "native"
        assert caps.level("provider_override") == "none"
        assert caps.supports_mcp is True

    def test_unknown_kwarg_raises(self) -> None:
        with pytest.raises(TypeError, match="Unknown RuntimeCapabilities"):
            RuntimeCapabilities("custom", "light", supports_wormholes=True)

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown support level"):
            RuntimeCapabilities("custom", "light", mcp="sometimes")  # type: ignore[arg-type]


class TestRuntimeConfigCapabilityValidation:
    """RuntimeConfig fail-fast validation of capability requirements."""

    def test_deepagents_portable_hitl_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="hitl"):
            RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="portable",
                required_capabilities=CapabilityRequirements(flags=("hitl",)),
            )

    def test_deepagents_native_mode_hitl_requirement_passes(self) -> None:
        config = RuntimeConfig(
            runtime_name="deepagents",
            feature_mode="native_first",
            required_capabilities=CapabilityRequirements(flags=("hitl",)),
        )
        assert config.feature_mode == "native_first"

    def test_deepagents_builtin_memory_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="builtin_memory"):
            RuntimeConfig(
                runtime_name="deepagents",
                required_capabilities=CapabilityRequirements(flags=("builtin_memory",)),
            )

    def test_deepagents_builtin_compaction_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="builtin_compaction"):
            RuntimeConfig(
                runtime_name="deepagents",
                required_capabilities=CapabilityRequirements(
                    flags=("builtin_compaction",)
                ),
            )

    def test_thin_native_mcp_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="mcp:native"):
            RuntimeConfig(
                runtime_name="thin",
                required_capabilities=CapabilityRequirements(flags=("mcp:native",)),
            )
