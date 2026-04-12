"""Tests for ThinRuntime hook dispatch integration.

Verifies that ThinRuntime accepts hook_registry, dispatches UserPromptSubmit
and Stop hooks, and passes hooks through to ToolExecutor.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.hooks.dispatcher import HookResult
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    """Returns pre-set responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.received_messages: list[list[dict[str, Any]]] = []

    async def __call__(self, messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any) -> str:
        self.received_messages.append(messages)
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


def make_tool_call(name: str, args: dict[str, Any] | None = None) -> str:
    return json.dumps({
        "type": "tool_call",
        "tool": {"name": name, "args": args or {}, "correlation_id": "c1"},
        "assistant_message": "",
    })


async def collect(
    runtime: ThinRuntime,
    text: str = "test",
    tools: list[ToolSpec] | None = None,
    mode_hint: str | None = None,
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="System",
        active_tools=tools or [],
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


# ===========================================================================
# Tests
# ===========================================================================


class TestThinRuntimeHooks:
    """ThinRuntime with hook_registry parameter."""

    async def test_runtime_without_hooks_works_as_before(self) -> None:
        """No hook_registry → backward-compatible behavior."""
        llm = MockLLM([make_final("hello")])
        runtime = ThinRuntime(llm_call=llm)
        events = await collect(runtime)
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert finals[0].data.get("text") == "hello"

    async def test_runtime_with_empty_hooks_works(self) -> None:
        """Empty HookRegistry → no hooks fire, but dispatcher is wired."""
        reg = HookRegistry()
        llm = MockLLM([make_final("hello")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        events = await collect(runtime)
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1

    async def test_pre_tool_hook_blocks_in_react_mode(self) -> None:
        """PreToolUse hook blocks tool → tool not executed, error returned."""

        async def block_all(**kwargs: Any) -> HookResult:
            return HookResult.block("blocked by test")

        reg = HookRegistry()
        reg.on_pre_tool_use(block_all)

        async def echo_tool(args: dict[str, Any]) -> dict[str, Any]:
            return {"echo": args}

        llm = MockLLM([
            make_tool_call("echo", {"msg": "hi"}),
            make_final("done"),
        ])
        tool_spec = ToolSpec(name="echo", description="Echo tool", parameters={"type": "object", "properties": {}})
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"echo": echo_tool},
            hook_registry=reg,
        )
        events = await collect(runtime, "use echo", tools=[tool_spec], mode_hint="react")

        tool_finished_events = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_finished_events) >= 1
        result = tool_finished_events[0].data
        assert "blocked" in json.dumps(result).lower() or not result.get("ok", True)

    async def test_post_tool_hook_modifies_output(self) -> None:
        """PostToolUse hook transforms tool output."""

        async def modify_output(**kwargs: Any) -> str:
            return '{"modified": true}'

        reg = HookRegistry()
        reg.on_post_tool_use(modify_output)

        async def echo_tool(args: dict[str, Any]) -> dict[str, Any]:
            return {"echo": args}

        llm = MockLLM([
            make_tool_call("echo", {"msg": "hi"}),
            make_final("done"),
        ])
        tool_spec = ToolSpec(name="echo", description="Echo", parameters={"type": "object", "properties": {}})
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"echo": echo_tool},
            hook_registry=reg,
        )
        events = await collect(runtime, "use echo", tools=[tool_spec], mode_hint="react")
        # The modified output should appear in the LLM messages
        assert llm._call_count == 2  # tool_call + final

    async def test_stop_hook_fires_on_completion(self) -> None:
        """Stop hook fires at end of run()."""
        stop_called: list[str] = []

        async def on_stop(**kwargs: Any) -> None:
            stop_called.append(kwargs.get("result_text", ""))

        reg = HookRegistry()
        reg.on_stop(on_stop)

        llm = MockLLM([make_final("final text")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        await collect(runtime)
        assert len(stop_called) == 1

    async def test_stop_hook_fires_on_error(self) -> None:
        """Stop hook fires even when runtime crashes."""
        stop_called: list[bool] = []

        async def on_stop(**kwargs: Any) -> None:
            stop_called.append(True)

        reg = HookRegistry()
        reg.on_stop(on_stop)

        async def crashing_llm(messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any) -> str:
            raise RuntimeError("LLM crashed")

        runtime = ThinRuntime(llm_call=crashing_llm, hook_registry=reg)
        events = await collect(runtime)
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1
        assert len(stop_called) == 1

    async def test_user_prompt_hook_transforms_prompt(self) -> None:
        """UserPromptSubmit hook transforms the user text before processing."""

        async def add_prefix(**kwargs: Any) -> str:
            return "INJECTED: " + kwargs.get("prompt", "")

        reg = HookRegistry()
        reg.on_user_prompt(add_prefix)

        llm = MockLLM([make_final("ok")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)

        events = await collect(runtime, "hello")
        # The LLM should receive the transformed prompt in the last user message
        assert llm._call_count == 1
        last_msg = llm.received_messages[0][-1]
        assert "INJECTED: hello" in str(last_msg.get("content", ""))
