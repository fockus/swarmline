"""Unit: AgentConfig - frozen configuration Agent facade."""

from __future__ import annotations

import dataclasses

import pytest
from cognitia.agent import Agent
from cognitia.agent.config import AgentConfig
from cognitia.runtime.capabilities import CapabilityRequirements, RuntimeCapabilities


class TestAgentConfigDefaults:
    """Konstruktor with minimumom parameterov."""

    def test_minimal_config(self) -> None:
        """system_prompt - edinstvennyy required, ostalnoe defaults."""
        cfg = AgentConfig(system_prompt="Ты — помощник")
        assert cfg.system_prompt == "Ты — помощник"
        assert cfg.model == "sonnet"
        assert cfg.runtime == "claude_sdk"
        assert cfg.tools == ()
        assert cfg.middleware == ()
        assert cfg.mcp_servers == {}
        assert cfg.hooks is None
        assert cfg.max_turns is None
        assert cfg.max_budget_usd is None
        assert cfg.output_format is None
        assert cfg.cwd is None
        assert cfg.env == {}
        assert cfg.betas == ()
        assert cfg.sandbox is None
        assert cfg.max_thinking_tokens is None
        assert cfg.fallback_model is None
        assert cfg.permission_mode == "bypassPermissions"
        assert cfg.feature_mode == "portable"
        assert cfg.require_capabilities is None
        assert cfg.allow_native_features is False
        assert cfg.native_config == {}
        assert cfg.setting_sources == ()


class TestAgentConfigFull:
    """Vse polya zadany."""

    def test_all_fields_set(self) -> None:
        """Konstruktor with polnym setom parameterov."""
        cfg = AgentConfig(
            system_prompt="test",
            model="opus",
            runtime="claude_sdk",
            tools=(),
            middleware=(),
            mcp_servers={"iss": {"type": "http", "url": "http://iss.test"}},
            hooks=None,
            max_turns=10,
            max_budget_usd=5.0,
            output_format={"type": "json_schema", "schema": {"type": "object"}},
            cwd="/tmp",
            env={"KEY": "val"},
            betas=("context-1m-2025-08-07",),
            sandbox={"enabled": True},
            max_thinking_tokens=32000,
            fallback_model="haiku",
            permission_mode="default",
            feature_mode="hybrid",
            require_capabilities=CapabilityRequirements(tier="full"),
            allow_native_features=True,
            native_config={"deepagents": {"use_native_todo": True}},
            setting_sources=("project", "user"),
        )
        assert cfg.model == "opus"
        assert cfg.runtime == "claude_sdk"
        assert cfg.max_turns == 10
        assert cfg.max_budget_usd == 5.0
        assert cfg.cwd == "/tmp"
        assert cfg.env == {"KEY": "val"}
        assert cfg.betas == ("context-1m-2025-08-07",)
        assert cfg.sandbox == {"enabled": True}
        assert cfg.max_thinking_tokens == 32000
        assert cfg.fallback_model == "haiku"
        assert cfg.permission_mode == "default"
        assert cfg.feature_mode == "hybrid"
        assert cfg.require_capabilities == CapabilityRequirements(tier="full")
        assert cfg.allow_native_features is True
        assert cfg.native_config == {"deepagents": {"use_native_todo": True}}
        assert cfg.setting_sources == ("project", "user")


class TestAgentConfigImmutable:
    """Frozen dataclass - notlzya mutirovat."""

    def test_frozen(self) -> None:
        cfg = AgentConfig(system_prompt="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.model = "opus"  # type: ignore[misc]

    def test_frozen_env(self) -> None:
        """env dict notlzya perenaznachit (no sam dict mutable - eto OK for frozen)."""
        cfg = AgentConfig(system_prompt="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.env = {"NEW": "val"}  # type: ignore[misc]


class TestAgentConfigValidation:
    """DTO-level validation pri createdii."""

    def test_empty_system_prompt_raises(self) -> None:
        """Empty system_prompt -> ValueError."""
        with pytest.raises(ValueError, match="system_prompt"):
            AgentConfig(system_prompt="")

    def test_whitespace_system_prompt_raises(self) -> None:
        """Tolko probely -> ValueError."""
        with pytest.raises(ValueError, match="system_prompt"):
            AgentConfig(system_prompt="   ")

    def test_invalid_runtime_is_allowed_at_dto_layer(self) -> None:
        """Runtime validation now happens at runtime/bootstrap boundary."""
        cfg = AgentConfig(system_prompt="test", runtime="unknown_runtime")
        assert cfg.runtime == "unknown_runtime"

    def test_invalid_feature_mode_is_allowed_at_dto_layer(self) -> None:
        """feature_mode validation now happens at runtime/bootstrap boundary."""
        cfg = AgentConfig(system_prompt="test", feature_mode="invalid_mode")
        assert cfg.feature_mode == "invalid_mode"

    def test_runtime_requirements_allowed_at_dto_layer(self) -> None:
        """Capability negotiation moves to runtime/bootstrap boundary."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            require_capabilities=CapabilityRequirements(tier="full"),
        )
        assert cfg.require_capabilities == CapabilityRequirements(tier="full")

    def test_custom_runtime_from_registry_is_accepted(self) -> None:
        """DTO stores custom runtime names without needing constructor validation."""
        from cognitia.runtime.registry import get_default_registry

        registry = get_default_registry()
        caps = RuntimeCapabilities(runtime_name="custom_agent_rt", tier="light")
        registry.register("custom_agent_rt", lambda config, **kwargs: object(), capabilities=caps)
        try:
            cfg = AgentConfig(
                system_prompt="test",
                runtime="custom_agent_rt",
                require_capabilities=CapabilityRequirements(tier="light"),
            )
            assert cfg.runtime == "custom_agent_rt"
        finally:
            registry.unregister("custom_agent_rt")


class TestAgentRuntimeBoundaryValidation:
    """Runtime/bootstrap boundary must fail fast on invalid AgentConfig."""

    def test_agent_rejects_invalid_runtime(self) -> None:
        with pytest.raises(ValueError, match="runtime"):
            Agent(AgentConfig(system_prompt="test", runtime="unknown_runtime"))

    def test_agent_rejects_invalid_feature_mode(self) -> None:
        with pytest.raises(ValueError, match="feature_mode"):
            Agent(AgentConfig(system_prompt="test", feature_mode="invalid_mode"))

    def test_agent_rejects_missing_capabilities(self) -> None:
        with pytest.raises(ValueError, match="thin"):
            Agent(
                AgentConfig(
                    system_prompt="test",
                    runtime="thin",
                    require_capabilities=CapabilityRequirements(tier="full"),
                )
            )

    def test_agent_accepts_registry_registered_runtime(self) -> None:
        from cognitia.runtime.registry import get_default_registry

        registry = get_default_registry()
        caps = RuntimeCapabilities(runtime_name="custom_agent_rt", tier="light")
        registry.register("custom_agent_rt", lambda config, **kwargs: object(), capabilities=caps)
        try:
            agent = Agent(
                AgentConfig(
                    system_prompt="test",
                    runtime="custom_agent_rt",
                    require_capabilities=CapabilityRequirements(tier="light"),
                )
            )
            assert agent.config.runtime == "custom_agent_rt"
        finally:
            registry.unregister("custom_agent_rt")


class TestAgentConfigModelResolution:
    """Alias models -> full imya (cherez resolve_model_name)."""

    def test_alias_sonnet(self) -> None:
        cfg = AgentConfig(system_prompt="test", model="sonnet")
        assert cfg.resolved_model.startswith("claude-sonnet")

    def test_alias_opus(self) -> None:
        cfg = AgentConfig(system_prompt="test", model="opus")
        assert cfg.resolved_model.startswith("claude-opus")

    def test_full_name_passthrough(self) -> None:
        cfg = AgentConfig(system_prompt="test", model="claude-sonnet-4-20250514")
        assert cfg.resolved_model == "claude-sonnet-4-20250514"

    def test_explicit_provider_prefix_passthrough(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            model="openrouter:anthropic/claude-3.5-haiku",
        )
        assert cfg.resolved_model == "openrouter:anthropic/claude-3.5-haiku"
