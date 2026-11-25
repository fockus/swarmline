"""Sprint 1ce Stage 3 (verifier fixes): per-run state must not leak across runs.

* The native-usage accumulator is scoped to ONE ``ThinRuntime`` run: a nested run
  started inside a tool (same asyncio task, same ContextVar) must neither wipe
  nor consume the parent's totals.
* A child spawned by ``ThinSubagentOrchestrator`` must not inherit the parent
  run's live plan provider / recitation settings — that is the parent's plan.
* ``native_config["max_tool_calls"]`` sets the run's tool-call budget (AGR-074):
  hosts size it to their turn budget instead of swarmline's default of 8.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from typing import Any

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.context.recitation_input_filter import RecitationInputFilter
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.thin.usage import (
    begin_native_usage_scope,
    consume_native_usage,
    end_native_usage_scope,
    record_native_usage,
    reset_native_usage,
)
from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec


@pytest.fixture(autouse=True)
def _clean_usage_channel():
    reset_native_usage()
    yield
    reset_native_usage()


def _recording_llm(script: list[tuple[str, int, int]]):
    """A text-ReAct ``llm_call`` that records usage like a provider adapter does."""
    queue = list(script)

    async def _call(messages, system_prompt, **kwargs):
        raw, input_tokens, output_tokens = queue.pop(0)
        record_native_usage(
            input_tokens, output_tokens, cache_read_tokens=input_tokens // 10
        )
        return raw

    return _call


def _final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


async def _final_usage(runtime: ThinRuntime, tools: list[ToolSpec]) -> dict[str, Any]:
    events = [
        ev
        async for ev in runtime.run(
            messages=[Message(role="user", content="go")],
            system_prompt="sys",
            active_tools=tools,
            mode_hint="react" if tools else None,
        )
    ]
    finals = [ev for ev in events if ev.type == "final"]
    assert len(finals) == 1, [(ev.type, ev.data) for ev in events]
    return finals[0].data["usage"]


async def test_nested_run_inside_a_tool_keeps_parent_usage_totals() -> None:
    child_usage: dict[str, Any] = {}

    async def delegate(task: str) -> str:
        child = ThinRuntime(
            llm_call=_recording_llm([(_final("child done"), 1_000, 100)])
        )
        child_usage.update(await _final_usage(child, []))
        return "delegated"

    parent = ThinRuntime(
        llm_call=_recording_llm(
            [
                (
                    json.dumps(
                        {
                            "type": "tool_call",
                            "tool": {"name": "delegate", "args": {"task": "x"}},
                        }
                    ),
                    100,
                    10,
                ),
                (_final("parent done"), 200, 20),
            ]
        ),
        local_tools={"delegate": delegate},
    )
    spec = ToolSpec(
        name="delegate",
        description="d",
        parameters={"type": "object", "properties": {"task": {"type": "string"}}},
    )

    parent_usage = await _final_usage(parent, [spec])

    assert (child_usage["input_tokens"], child_usage["output_tokens"]) == (1_000, 100)
    assert (parent_usage["input_tokens"], parent_usage["output_tokens"]) == (300, 30)
    assert parent_usage["cache_read_tokens"] == 30


async def test_run_restores_the_callers_usage_after_it_ends() -> None:
    # Whatever the caller had accumulated before a run is back once the run ends.
    record_native_usage(7, 3)
    runtime = ThinRuntime(llm_call=_recording_llm([(_final("ok"), 50, 5)]))

    usage = await _final_usage(runtime, [])

    from swarmline.runtime.thin.usage import consume_native_usage

    assert (usage["input_tokens"], usage["output_tokens"]) == (50, 5)
    assert consume_native_usage() == {"input_tokens": 7, "output_tokens": 3}


def test_subagent_does_not_inherit_parent_recitation_settings() -> None:
    async def _parent_plan() -> str:
        return "the parent's todo list"

    parent_native = {
        "recitation_plan_provider": _parent_plan,
        "recitation_round_cadence": 2,
        "recitation_plan_text": "parent plan",
        "recitation_plan_summary_text": "parent plan (short)",
        "recitation_cadence": 5,
        "prompt_caching_enabled": True,
    }
    kept_filter = object()
    orchestrator = ThinSubagentOrchestrator(
        runtime_config=RuntimeConfig(
            runtime_name="thin",
            native_config=parent_native,
            input_filters=[RecitationInputFilter(plan_text="parent plan"), kept_filter],
        ),
    )

    worker = orchestrator._create_runtime(SubagentSpec(name="w", system_prompt="p"))

    assert worker._runtime_config.native_config == {"prompt_caching_enabled": True}
    assert worker._runtime_config.input_filters == [kept_filter]
    assert parent_native["recitation_plan_provider"] is _parent_plan, (
        "parent config untouched"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(120, 120), (100.0, 100), (None, 8), ("120", 8), (True, 8), (0, 8)],
)
def test_native_config_max_tool_calls_sets_the_run_tool_budget(
    raw: object, expected: int
) -> None:
    native = {} if raw is None else {"max_tool_calls": raw}
    plan = build_portable_runtime_plan(
        AgentConfig(system_prompt="s", runtime="thin", native_config=native), "thin"
    )

    assert plan.config.max_tool_calls == expected


# --- the scope is restored on every way a nested run can end ---------------

_DELEGATE = ToolSpec(
    name="delegate",
    description="d",
    parameters={"type": "object", "properties": {"task": {"type": "string"}}},
)
_CALL = json.dumps(
    {"type": "tool_call", "tool": {"name": "delegate", "args": {"task": "x"}}}
)


async def _parent_totals(delegate) -> tuple[int, int]:
    parent = ThinRuntime(
        llm_call=_recording_llm([(_CALL, 100, 10), (_final("parent done"), 200, 20)]),
        local_tools={"delegate": delegate},
    )
    usage = await _final_usage(parent, [_DELEGATE])
    return usage["input_tokens"], usage["output_tokens"]


async def test_child_run_that_raises_keeps_parent_usage_totals() -> None:
    async def delegate(task: str) -> str:
        async def _failing(messages, system_prompt, **kwargs):
            record_native_usage(1_000, 100)
            raise RuntimeError("provider down")

        child = ThinRuntime(llm_call=_failing)
        [
            ev
            async for ev in child.run(
                messages=[Message(role="user", content="c")],
                system_prompt="s",
                active_tools=[],
            )
        ]
        return "child failed"

    assert await _parent_totals(delegate) == (300, 30)


async def test_child_run_closed_early_keeps_parent_usage_totals() -> None:
    async def delegate(task: str) -> str:
        child = ThinRuntime(llm_call=_recording_llm([(_final("child"), 1_000, 100)]))
        stream = child.run(
            messages=[Message(role="user", content="c")],
            system_prompt="s",
            active_tools=[],
        )
        async for _ in stream:
            break
        await stream.aclose()
        return "abandoned"

    assert await _parent_totals(delegate) == (300, 30)


async def test_child_run_cancelled_by_timeout_keeps_parent_usage_totals() -> None:
    async def delegate(task: str) -> str:
        async def _slow(messages, system_prompt, **kwargs):
            record_native_usage(1_000, 100)
            await asyncio.sleep(10)

        child = ThinRuntime(llm_call=_slow)
        try:
            async with asyncio.timeout(0.05):
                [
                    ev
                    async for ev in child.run(
                        messages=[Message(role="user", content="c")],
                        system_prompt="s",
                        active_tools=[],
                    )
                ]
        except TimeoutError:
            pass
        return "timed out"

    assert await _parent_totals(delegate) == (300, 30)


def test_end_scope_from_a_foreign_context_is_a_no_op() -> None:
    # A token set in another context (an abandoned generator finalized elsewhere)
    # cannot be reset here: the call must neither raise nor touch local totals.
    record_native_usage(5, 1)
    foreign_token = contextvars.copy_context().run(begin_native_usage_scope)

    end_native_usage_scope(foreign_token)

    assert consume_native_usage() == {"input_tokens": 5, "output_tokens": 1}
