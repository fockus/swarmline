"""Tests for command_registry wiring from AgentConfig to ThinRuntime create_kwargs.

Verifies that AgentConfig.command_registry flows through
build_portable_runtime_plan into create_kwargs.
"""

from __future__ import annotations

from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.commands.registry import CommandRegistry


def _make_config(**overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = {"system_prompt": "test prompt", "runtime": "thin"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestCommandWiring:
    """Command registry flows from AgentConfig through build_portable_runtime_plan."""

    def test_command_registry_wiring(self) -> None:
        """AgentConfig(command_registry=reg) -> create_kwargs contains registry."""
        registry = CommandRegistry()

        async def handler(*args: Any, **kwargs: Any) -> str:
            return "ok"

        registry.add("test", handler=handler)

        config = _make_config(command_registry=registry)
        plan = build_portable_runtime_plan(config, "thin")

        assert plan.create_kwargs.get("command_registry") is registry

    def test_no_command_registry_wiring(self) -> None:
        """AgentConfig() (no registry) -> create_kwargs does NOT contain command_registry."""
        config = _make_config()
        plan = build_portable_runtime_plan(config, "thin")

        assert "command_registry" not in plan.create_kwargs
