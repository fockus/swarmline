"""Tests for CodingProfileConfig — CADG-01: opt-in coding profile.

RED phase: tests define the contract, implementation is scaffold-only.
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.runtime.thin.coding_profile import CodingProfileConfig


class TestCodingProfileConfigContract:
    """CodingProfileConfig is a frozen dataclass with sensible defaults."""

    def test_default_enabled_true(self) -> None:
        """Default profile has enabled=True."""
        cfg = CodingProfileConfig()
        assert cfg.enabled is True

    def test_explicit_disabled(self) -> None:
        """Profile can be explicitly disabled."""
        cfg = CodingProfileConfig(enabled=False)
        assert cfg.enabled is False

    def test_frozen_immutable(self) -> None:
        """Profile config is frozen — mutation raises."""
        cfg = CodingProfileConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.enabled = False  # type: ignore[misc]

    def test_is_dataclass(self) -> None:
        """CodingProfileConfig is a proper dataclass."""
        assert dataclasses.is_dataclass(CodingProfileConfig)
        assert dataclasses.is_dataclass(CodingProfileConfig())

    def test_equality_value_based(self) -> None:
        """Two configs with same values are equal."""
        a = CodingProfileConfig(enabled=True)
        b = CodingProfileConfig(enabled=True)
        assert a == b

    def test_inequality_different_enabled(self) -> None:
        """Configs with different enabled are not equal."""
        a = CodingProfileConfig(enabled=True)
        b = CodingProfileConfig(enabled=False)
        assert a != b


class TestCodingProfileOnAgentConfig:
    """CADG-01: AgentConfig accepts coding_profile without new runtime hierarchy."""

    def test_agent_config_accepts_coding_profile_none_default(self) -> None:
        """AgentConfig.coding_profile defaults to None."""
        from swarmline.agent.config import AgentConfig

        cfg = AgentConfig(system_prompt="test")
        assert cfg.coding_profile is None

    def test_agent_config_accepts_coding_profile_value(self) -> None:
        """AgentConfig accepts CodingProfileConfig."""
        from swarmline.agent.config import AgentConfig

        profile = CodingProfileConfig(enabled=True)
        cfg = AgentConfig(system_prompt="test", coding_profile=profile)
        assert cfg.coding_profile is profile
        assert cfg.coding_profile.enabled is True

    def test_agent_config_runtime_unchanged(self) -> None:
        """Setting coding_profile does NOT change runtime field — no new hierarchy."""
        from swarmline.agent.config import AgentConfig

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(),
        )
        assert cfg.runtime == "thin"

    def test_default_allow_host_execution_true(self) -> None:
        """Default profile allows host execution."""
        cfg = CodingProfileConfig()
        assert cfg.allow_host_execution is True

    def test_read_only_profile(self) -> None:
        """Profile can disable host execution for read-only mode."""
        cfg = CodingProfileConfig(allow_host_execution=False)
        assert cfg.allow_host_execution is False
        assert cfg.enabled is True

    def test_wiring_requires_cwd_when_coding_profile_enabled(self) -> None:
        """build_portable_runtime_plan raises if cwd is None with coding profile."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            # cwd intentionally omitted → None
        )
        with pytest.raises(ValueError, match="cwd is required"):
            build_portable_runtime_plan(cfg, "thin")
