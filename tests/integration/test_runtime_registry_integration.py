"""Integration tests for RuntimeRegistry — full flow with factory and validation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.types import RuntimeConfig, RuntimeEvent

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCustomRuntime:
    """Minimal fake runtime for integration tests."""

    def __init__(self, config: RuntimeConfig, **kwargs: Any) -> None:
        self.config = config
        self.kwargs = kwargs

    async def run(
        self,
        *,
        messages: list[Any] | None = None,
        system_prompt: str = "",
        active_tools: list[Any] | None = None,
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        yield RuntimeEvent.status("custom runtime running")
        yield RuntimeEvent.final(text="custom response")

    async def cleanup(self) -> None:
        pass


def _custom_factory(config: RuntimeConfig, **kwargs: Any) -> FakeCustomRuntime:
    return FakeCustomRuntime(config=config, **kwargs)


_CUSTOM_CAPS = RuntimeCapabilities(runtime_name="custom_int", tier="light")


# ---------------------------------------------------------------------------
# Full flow tests
# ---------------------------------------------------------------------------


class TestRegisterCustomRuntimeFullFlow:
    """Register custom runtime -> create via factory -> run -> events."""

    @pytest.mark.asyncio
    async def test_register_create_run_events(self) -> None:
        """Full lifecycle: register -> factory.create -> run -> get events."""
        from swarmline.runtime.factory import RuntimeFactory
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        registry.register("custom_int", _custom_factory, capabilities=_CUSTOM_CAPS)

        factory = RuntimeFactory(registry=registry)

        # Build config bypassing __post_init__ validation (custom name not in global set)
        cfg = RuntimeConfig.__new__(RuntimeConfig)
        object.__setattr__(cfg, "runtime_name", "custom_int")
        object.__setattr__(cfg, "feature_mode", "portable")
        object.__setattr__(cfg, "required_capabilities", None)
        object.__setattr__(cfg, "output_type", None)
        object.__setattr__(cfg, "output_format", None)
        object.__setattr__(cfg, "max_iterations", 6)
        object.__setattr__(cfg, "max_tool_calls", 8)
        object.__setattr__(cfg, "max_model_retries", 2)
        object.__setattr__(cfg, "model", "claude-sonnet-4-20250514")
        object.__setattr__(cfg, "base_url", None)
        object.__setattr__(cfg, "extra", {})
        object.__setattr__(cfg, "allow_native_features", False)
        object.__setattr__(cfg, "native_config", {})

        runtime = factory.create(config=cfg)
        assert isinstance(runtime, FakeCustomRuntime)

        events = []
        async for event in runtime.run():
            events.append(event)

        assert len(events) == 2
        assert events[0].type == "status"
        assert events[1].type == "final"
        assert events[1].data["text"] == "custom response"


class TestFactoryBackwardCompatAllRuntimes:
    """All builtin runtimes create via registry-backed factory."""

    def test_all_builtins_creatable(self) -> None:
        """claude_sdk, deepagents, thin all create without crash via default registry."""
        from swarmline.runtime.factory import RuntimeFactory
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        factory = RuntimeFactory(registry=registry)

        for name in (
            "claude_sdk",
            "deepagents",
            "thin",
            "cli",
            "openai_agents",
            "pi_sdk",
        ):
            runtime = factory.create(config=RuntimeConfig(runtime_name=name))
            # May be real runtime or _ErrorRuntime (deps missing), but must not crash
            assert runtime is not None


class TestValidRuntimeNamesDynamic:
    """After registering custom runtime, name appears in valid set."""

    def test_custom_name_in_valid_set_after_register(self) -> None:
        """Dynamic get_valid_runtime_names() includes custom registered runtimes."""
        from swarmline.runtime.registry import (
            get_default_registry,
            get_valid_runtime_names,
        )

        registry = get_default_registry()
        caps = RuntimeCapabilities(runtime_name="dyn_test", tier="light")
        registry.register("dyn_test", _custom_factory, capabilities=caps)

        try:
            valid = get_valid_runtime_names()
            assert "dyn_test" in valid
            # Builtins still present
            assert "claude_sdk" in valid
            assert "thin" in valid
        finally:
            registry.unregister("dyn_test")
