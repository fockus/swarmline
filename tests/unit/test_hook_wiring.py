"""Tests for hooks wiring through Agent config → RuntimeFactory → ThinRuntime.

Verifies that hooks from AgentConfig.hooks and middleware.get_hooks() are
merged and passed to ThinRuntime via build_portable_runtime_plan.
"""

from __future__ import annotations

from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import SecurityGuard
from swarmline.hooks.registry import HookRegistry


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt", "runtime": "thin"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestHookWiring:
    """Hooks flow from AgentConfig through build_portable_runtime_plan."""

    def test_hooks_from_config_reach_create_kwargs(self) -> None:
        """AgentConfig.hooks → create_kwargs['hook_registry']."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        reg = HookRegistry()

        async def dummy(**kwargs: Any) -> None:
            pass

        reg.on_stop(dummy)
        config = _make_config(hooks=reg)
        plan = build_portable_runtime_plan(config, "thin")
        assert plan.create_kwargs.get("hook_registry") is reg

    def test_middleware_hooks_merged_into_create_kwargs(self) -> None:
        """Middleware.get_hooks() merged with config.hooks → create_kwargs."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        guard = SecurityGuard(block_patterns=["rm -rf"])
        config = _make_config(middleware=(guard,))
        plan = build_portable_runtime_plan(config, "thin")

        merged_registry = plan.create_kwargs.get("hook_registry")
        assert merged_registry is not None
        assert len(merged_registry.get_hooks("PreToolUse")) >= 1

    def test_no_hooks_no_dispatcher(self) -> None:
        """No hooks + no middleware → hook_registry absent from create_kwargs."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config()
        plan = build_portable_runtime_plan(config, "thin")
        assert "hook_registry" not in plan.create_kwargs
