"""Tests for react_strategy opt-in use_iteration_budget flag (OSS-T3).

TDD Red phase: tests before implementation.
Covers:
- Byte-identical default: use_iteration_budget=False produces same cap as
  the plain ``iterations < config.max_iterations`` guard.
- Opt-in: use_iteration_budget=True produces identical cap (VO-driven path).
"""

from __future__ import annotations

import json

import pytest

from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InfiniteToolCallLLM:
    """Returns tool_call responses indefinitely to drive the loop to its cap."""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        return json.dumps({"type": "tool_call", "tool": {"name": "noop", "args": {}}})


def _noop_tool(**kwargs: object) -> str:
    return json.dumps({"result": "ok"})


async def _collect_events(runtime: ThinRuntime) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="go")],
        system_prompt="You are a helper.",
        active_tools=[ToolSpec(name="noop", description="do nothing", parameters={})],
        mode_hint="react",
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Default: use_iteration_budget=False
# ---------------------------------------------------------------------------


class TestReactIterationBudgetDefault:
    """Default flag OFF — behaviour must be byte-identical to pre-OSS-T3."""

    def test_default_flag_is_false(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        assert config.use_iteration_budget is False

    @pytest.mark.asyncio
    async def test_loop_limit_error_emitted_at_max_iterations(self) -> None:
        """Loop cap triggers loop_limit error after max_iterations turns."""
        max_iter = 3
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=False,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )
        events = await _collect_events(runtime)
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "loop_limit"

    @pytest.mark.asyncio
    async def test_tool_call_count_equals_max_iterations(self) -> None:
        """LLM called exactly max_iterations times; confirms no early exit."""
        max_iter = 4
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=False,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )
        events = await _collect_events(runtime)
        tool_starts = [e for e in events if e.type == "tool_call_started"]
        assert len(tool_starts) == max_iter


# ---------------------------------------------------------------------------
# Opt-in: use_iteration_budget=True
# ---------------------------------------------------------------------------


class TestReactIterationBudgetOptIn:
    """Flag ON — VO-driven path must produce identical cap to the default."""

    @pytest.mark.asyncio
    async def test_loop_limit_error_emitted_at_max_iterations_with_flag(self) -> None:
        """With flag, loop_limit error still fires at exactly max_iterations."""
        max_iter = 3
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=True,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )
        events = await _collect_events(runtime)
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "loop_limit"

    @pytest.mark.asyncio
    async def test_tool_call_count_equals_max_iterations_with_flag(self) -> None:
        """VO path: LLM called exactly max_iterations times."""
        max_iter = 4
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=True,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )
        events = await _collect_events(runtime)
        tool_starts = [e for e in events if e.type == "tool_call_started"]
        assert len(tool_starts) == max_iter

    @pytest.mark.asyncio
    async def test_flag_and_default_produce_identical_tool_call_counts(self) -> None:
        """VO-path and int-path produce the same number of tool call events."""
        max_iter = 5
        llm_off = _InfiniteToolCallLLM()
        llm_on = _InfiniteToolCallLLM()

        cfg_off = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=False,
        )
        cfg_on = RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iter,
            max_tool_calls=1000,
            use_iteration_budget=True,
        )

        rt_off = ThinRuntime(
            llm_call=llm_off, local_tools={"noop": _noop_tool}, config=cfg_off
        )
        rt_on = ThinRuntime(
            llm_call=llm_on, local_tools={"noop": _noop_tool}, config=cfg_on
        )

        events_off = await _collect_events(rt_off)
        events_on = await _collect_events(rt_on)

        starts_off = [e for e in events_off if e.type == "tool_call_started"]
        starts_on = [e for e in events_on if e.type == "tool_call_started"]
        assert len(starts_off) == len(starts_on) == max_iter
