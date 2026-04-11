"""Unit: runtime capability descriptors and trebovaniya."""

from __future__ import annotations

import pytest
from swarmline.runtime.capabilities import (
    CapabilityRequirements,
    get_runtime_capabilities,
)
from swarmline.runtime.types import RuntimeConfig


class TestCapabilityRequirements:
    """CapabilityRequirements - validation and sravnotnie."""

    def test_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="tier"):
            CapabilityRequirements(tier="unknown")  # type: ignore[arg-type]

    def test_invalid_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown capability flags"):
            CapabilityRequirements(flags=("unknown_flag",))


class TestRuntimeCapabilities:
    """get_runtime_capabilities() — descriptor per runtime."""

    def test_claude_sdk_is_full_tier(self) -> None:
        caps = get_runtime_capabilities("claude_sdk")
        assert caps.runtime_name == "claude_sdk"
        assert caps.tier == "full"
        assert caps.supports_mcp is True
        assert caps.supports_interrupt is True
        assert caps.supports_resume is True

    def test_deepagents_is_full_tier(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        assert caps.runtime_name == "deepagents"
        assert caps.tier == "full"
        assert caps.supports_resume is True
        assert caps.supports_interrupt is False
        assert caps.supports_user_input is False
        assert caps.supports_hitl is False
        assert caps.supports_builtin_memory is False
        assert caps.supports_builtin_compaction is False
        assert caps.supports_builtin_todo is True
        assert caps.supports_native_subagents is True
        assert caps.supports_provider_override is True

    def test_thin_is_light_tier(self) -> None:
        caps = get_runtime_capabilities("thin")
        assert caps.runtime_name == "thin"
        assert caps.tier == "light"
        assert caps.supports_provider_override is True

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

    def test_deepagents_reports_hitl_as_missing(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        req = CapabilityRequirements(flags=("hitl",))
        assert caps.supports(req) is False
        assert caps.missing(req) == ("hitl",)

    def test_deepagents_reports_builtin_memory_as_missing(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        req = CapabilityRequirements(flags=("builtin_memory",))
        assert caps.supports(req) is False
        assert caps.missing(req) == ("builtin_memory",)

    def test_deepagents_reports_builtin_compaction_as_missing(self) -> None:
        caps = get_runtime_capabilities("deepagents")
        req = CapabilityRequirements(flags=("builtin_compaction",))
        assert caps.supports(req) is False
        assert caps.missing(req) == ("builtin_compaction",)


class TestRuntimeConfigCapabilityValidation:
    """RuntimeConfig fail-fast validation capability requirements."""

    def test_deepagents_portable_hitl_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="hitl"):
            RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="portable",
                required_capabilities=CapabilityRequirements(flags=("hitl",)),
            )

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

    def test_deepagents_builtin_memory_and_compaction_requirement_raises(self) -> None:
        with pytest.raises(ValueError, match="builtin_memory, builtin_compaction"):
            RuntimeConfig(
                runtime_name="deepagents",
                required_capabilities=CapabilityRequirements(
                    flags=("builtin_memory", "builtin_compaction")
                ),
            )
