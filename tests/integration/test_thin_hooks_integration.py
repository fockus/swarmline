"""Integration tests: SecurityGuard blocks tool via full ThinRuntime chain.

Uses REAL HookRegistry + DefaultHookDispatcher + SecurityGuard middleware.
No mocks except the LLM itself.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import SecurityGuard
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
    Message,
    RuntimeEvent,
    ToolSpec,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._i = 0

    async def __call__(
        self, messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any
    ) -> str:
        if self._i < len(self._responses):
            resp = self._responses[self._i]
            self._i += 1
            return resp
        return json.dumps({"type": "final", "final_message": "done"})


def _make_tool_call(name: str, args: dict[str, Any]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args, "correlation_id": "c1"},
            "assistant_message": "",
        }
    )


def _make_final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


async def _collect(
    runtime: ThinRuntime,
    text: str,
    tools: list[ToolSpec],
    mode_hint: str | None = None,
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="System",
        active_tools=tools,
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


class TestSecurityGuardIntegration:
    """SecurityGuard middleware blocks dangerous tool calls via ThinRuntime hooks."""

    @pytest.mark.integration
    async def test_security_guard_blocks_dangerous_tool_in_thin_runtime(self) -> None:
        """SecurityGuard with pattern 'rm -rf' blocks tool execution in full chain."""
        guard = SecurityGuard(block_patterns=["rm -rf"])
        merged_hooks = guard.get_hooks()

        tool_called = False

        async def shell_tool(command: str) -> str:
            nonlocal tool_called
            tool_called = True
            return f"executed: {command}"

        llm = MockLLM(
            [
                _make_tool_call("shell", {"command": "rm -rf /"}),
                _make_final("done"),
            ]
        )
        tool_spec = ToolSpec(
            name="shell",
            description="Shell",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
            },
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"shell": shell_tool},
            hook_registry=merged_hooks,
        )

        events = await _collect(runtime, "rm -rf /", [tool_spec], mode_hint="react")

        assert not tool_called, "SecurityGuard should have prevented tool execution"
        tool_finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_finished) >= 1
        result_data = tool_finished[0].data
        assert (
            not result_data.get("ok", True)
            or "block" in json.dumps(result_data).lower()
        )

    @pytest.mark.integration
    async def test_hooks_from_agent_config_reach_thin_runtime(self) -> None:
        """AgentConfig.hooks → build_portable_runtime_plan → ThinRuntime → ToolExecutor."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        guard = SecurityGuard(block_patterns=["DROP TABLE"])
        config = AgentConfig(
            system_prompt="test",
            runtime="thin",
            middleware=(guard,),
        )

        plan = build_portable_runtime_plan(config, "thin")

        # Verify hooks are in create_kwargs
        hook_registry = plan.create_kwargs.get("hook_registry")
        assert hook_registry is not None
        assert len(hook_registry.get_hooks("PreToolUse")) >= 1
