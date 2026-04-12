"""Cross-feature integration tests for Phases 1-5.

Validates that hooks, policy, subagents, commands, and native tools
interact correctly without conflicts.
"""

from __future__ import annotations

import json
from typing import Any

from swarmline.commands.registry import CommandRegistry
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _final_text(raw: str) -> str:
    return json.dumps({"type": "final", "final_message": raw})


class MockLLM:
    """Mock LLM that returns predefined responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.called = False

    async def __call__(self, messages: Any, system_prompt: str, **kwargs: Any) -> str:
        self.called = True
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        return _final_text("fallback")


async def _collect(runtime: ThinRuntime, text: str = "test") -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="System",
        active_tools=[],
    ):
        events.append(ev)
    return events


# ===========================================================================
# Tests
# ===========================================================================


class TestCrossFeatureIntegration:
    """Tests that verify features from different phases work together."""

    async def test_hooks_and_commands_interact(self) -> None:
        """UserPromptSubmit hook transforms text, then command intercept handles it."""
        # Hook: transform "greet" -> "/help"
        async def transform(**kwargs: Any) -> str:
            prompt = kwargs.get("prompt", "")
            if prompt == "greet":
                return "/help"
            return prompt

        hook_reg = HookRegistry()
        hook_reg.on_user_prompt(transform)

        cmd_reg = CommandRegistry()

        async def help_handler(*args: Any, **kwargs: Any) -> str:
            return "Help: available commands"

        cmd_reg.add("help", handler=help_handler)

        llm = MockLLM([])
        runtime = ThinRuntime(
            llm_call=llm, hook_registry=hook_reg, command_registry=cmd_reg,
        )

        events = await _collect(runtime, "greet")

        # Hook transformed "greet" -> "/help", command intercepted
        assert not llm.called
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "Help:" in finals[0].data["text"]

    async def test_command_fires_stop_hook(self) -> None:
        """Command intercept fires Stop hook (Phase 1 + Phase 4 interaction)."""
        stop_results: list[str] = []

        async def on_stop(**kwargs: Any) -> None:
            stop_results.append(kwargs.get("result_text", ""))

        hook_reg = HookRegistry()
        hook_reg.on_stop(on_stop)

        cmd_reg = CommandRegistry()

        async def status_handler(*args: Any, **kwargs: Any) -> str:
            return "Status: running"

        cmd_reg.add("status", handler=status_handler)

        runtime = ThinRuntime(
            llm_call=MockLLM([]),
            hook_registry=hook_reg,
            command_registry=cmd_reg,
        )

        await _collect(runtime, "/status")

        assert len(stop_results) == 1
        assert "Status: running" in stop_results[0]

    async def test_all_config_fields_optional(self) -> None:
        """All new AgentConfig/RuntimeConfig fields have None/False defaults."""
        from swarmline.agent.config import AgentConfig

        # AgentConfig with only required field
        config = AgentConfig(system_prompt="test")
        assert config.hooks is None
        assert config.tool_policy is None
        assert config.subagent_config is None
        assert config.command_registry is None

        # RuntimeConfig with defaults
        rc = RuntimeConfig()
        assert rc.use_native_tools is False

    async def test_unregistered_command_with_hooks_passes_to_llm(self) -> None:
        """Unregistered /command with hooks enabled passes through to LLM."""
        hook_reg = HookRegistry()
        cmd_reg = CommandRegistry()

        async def noop_handler(*args: Any, **kwargs: Any) -> str:
            return "ok"

        cmd_reg.add("known", handler=noop_handler)

        llm = MockLLM([_final_text("LLM handled /unknown")])
        runtime = ThinRuntime(
            llm_call=llm, hook_registry=hook_reg, command_registry=cmd_reg,
        )

        events = await _collect(runtime, "/unknown_cmd")

        assert llm.called
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1

    async def test_no_features_backward_compat(self) -> None:
        """ThinRuntime with no hooks/policy/commands/native works like before."""
        llm = MockLLM([_final_text("Hello world")])
        runtime = ThinRuntime(llm_call=llm)

        events = await _collect(runtime, "hi")

        assert llm.called
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Hello world"
