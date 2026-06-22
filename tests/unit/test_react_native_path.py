"""Fix B: native two-phase path in run_react (clean loop prompt + structured finalize).

Phase 1 = native tool loop with a CLEAN prompt (no ReAct envelope). Phase 2 = a separate
structured call carrying provider-native ``response_format`` when supported, validated via
``finalize_with_validation``. On any native error the loop falls back to text-ReAct silently.
No network: a fake native adapter + a recording ``llm_call`` stand in for the provider.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig, ToolSpec


class _Out(BaseModel):
    answer: str


_SCHEMA = _Out.model_json_schema()
_SYS = "SYSTEM-SENTINEL: you are a helper."


class _FakeNativeAdapter:
    def __init__(self, results: list[NativeToolCallResult]):
        self._results = results
        self.seen_prompts: list[str] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.seen_prompts.append(system_prompt)
        # Fail loudly with intent (not a bare IndexError) when the loop calls the adapter
        # more times than results were seeded — that signals a REAL loop bug, not a typo.
        assert self._results, (
            f"native adapter called {len(self.seen_prompts)} times but only "
            f"{len(self.seen_prompts) - 1} result(s) were seeded — the loop iterated more "
            "than the test expected"
        )
        return self._results.pop(0)


class _RecordingLlmCall:
    def __init__(self, raw: str):
        self._raw = raw
        self.calls: list[dict] = []

    async def __call__(self, messages, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return self._raw


class _SequencedLlmCall:
    """Recording ``llm_call`` returning a different canned raw per call (last one repeats).

    Drives the Phase-2 retry path: the first structured call returns malformed output, the
    next returns valid JSON — so ``finalize_with_validation`` must retry and recover.
    """

    def __init__(self, raws: list[str]):
        self._raws = list(raws)
        self.calls: list[dict] = []

    async def __call__(self, messages, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


def _config(**over) -> RuntimeConfig:
    base = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        use_native_tools=True,
        structured_mode="auto",
        output_type=_Out,
        output_format=_SCHEMA,
        max_iterations=6,
    )
    base.update(over)
    return RuntimeConfig(**base)


async def _drive(adapter, llm_call, config):
    events = []
    async for ev in run_react(
        llm_call,
        ToolExecutor(local_tools={}),
        messages=[],
        system_prompt=_SYS,
        tools=[
            ToolSpec(
                name="search",
                description="d",
                parameters={"type": "object", "properties": {}},
            )
        ],
        config=config,
        start_time=time.monotonic(),
        native_adapter=adapter,
    ):
        events.append(ev)
    return events


def _final(events):
    return [e for e in events if getattr(e, "type", None) == "final"]


def _errors(events):
    return [e for e in events if getattr(e, "type", None) == "error"]


# --- T2: clean native-loop prompt -------------------------------------------


@pytest.mark.asyncio
async def test_native_loop_prompt_is_clean_no_react_envelope() -> None:
    adapter = _FakeNativeAdapter([NativeToolCallResult(text="done", tool_calls=())])
    llm_call = _RecordingLlmCall('{"answer": "ok"}')
    await _drive(adapter, llm_call, _config())
    loop_prompt = adapter.seen_prompts[0]
    assert "SYSTEM-SENTINEL" in loop_prompt
    assert "Инструкции по формату ответа" not in loop_prompt
    assert "final_message" not in loop_prompt


# --- T3: two-phase structured finalization + auto-fallback -------------------


@pytest.mark.asyncio
async def test_phase2_makes_structured_call_with_response_format() -> None:
    adapter = _FakeNativeAdapter(
        [
            NativeToolCallResult(
                tool_calls=(NativeToolCall(id="c1", name="search", args={}),)
            ),
            NativeToolCallResult(text="here is my answer", tool_calls=()),
        ]
    )
    llm_call = _RecordingLlmCall('{"answer": "final"}')
    events = await _drive(adapter, llm_call, _config())
    finals = _final(events)
    assert finals, "expected a final event from Phase 2"
    assert finals[-1].data.get("structured_output") is not None
    assert "response_format" in llm_call.calls[-1]["kwargs"]  # OpenRouter → json_schema


@pytest.mark.asyncio
async def test_phase2_retries_on_malformed_then_succeeds() -> None:
    # Phase 2's FIRST structured call returns non-schema text; finalize_with_validation must
    # retry and the SECOND (valid) call yields the structured output — it must NOT error out
    # and (Fix B contract) must NOT fall back to text-ReAct on a finalization-level miss.
    adapter = _FakeNativeAdapter(
        [NativeToolCallResult(text="here is my answer", tool_calls=())]
    )
    llm_call = _SequencedLlmCall(["not json at all", '{"answer": "repaired"}'])
    events = await _drive(adapter, llm_call, _config(max_model_retries=2))
    finals = _final(events)
    assert finals, (
        "expected a final after Phase-2 retry recovered the structured output"
    )
    assert finals[-1].data.get("structured_output") is not None
    assert len(llm_call.calls) >= 2, (
        "Phase 2 must retry the structured call on malformed output"
    )
    assert not _errors(events), (
        "a recoverable Phase-2 miss must not surface as an error"
    )


@pytest.mark.asyncio
async def test_native_failure_falls_back_to_text_react() -> None:
    class _Boom:
        seen_prompts: list[str] = []

        async def call_with_tools(self, *a, **k):
            raise RuntimeError("native boom")

    llm_call = _RecordingLlmCall(
        '{"type": "final", "final_message": "{\\"answer\\": \\"viatext\\"}"}'
    )
    events = await _drive(_Boom(), llm_call, _config())
    assert not _errors(events), "native failure must fall back silently, not error"
    assert _final(events), "fallback text-ReAct path must still finalize"


@pytest.mark.asyncio
async def test_prompt_mode_never_uses_native_branch() -> None:
    adapter = _FakeNativeAdapter([NativeToolCallResult(text="x", tool_calls=())])
    llm_call = _RecordingLlmCall(
        '{"type": "final", "final_message": "{\\"answer\\": \\"p\\"}"}'
    )
    await _drive(
        adapter, llm_call, _config(structured_mode="prompt", use_native_tools=False)
    )
    assert adapter.seen_prompts == [], "prompt mode must not call the native adapter"


# --- Tool-budget exhaustion forces a finalize instead of erroring ------------


@pytest.mark.asyncio
async def test_tool_budget_exhaustion_forces_finalize_not_error() -> None:
    """A model that never stops requesting tools must still produce a best-effort answer.

    When ``tool_calls_count`` would exceed ``config.max_tool_calls`` the native loop must STOP
    calling tools and FORCE a Phase-2 structured finalize from the context gathered so far —
    rather than yielding a ``budget_exceeded`` error and losing everything (which surfaced to the
    caller as an empty ``StructuredOutputError`` and a broken recommend turn). Graceful
    degradation, not a crash.
    """
    # max_tool_calls=1: iter 1 executes the tool (count→1); iter 2's request trips the budget
    # (1 + 1 > 1) and must force-finalize. Two tool-call results are seeded for the two iterations.
    adapter = _FakeNativeAdapter(
        [
            NativeToolCallResult(
                tool_calls=(NativeToolCall(id="c1", name="search", args={}),)
            ),
            NativeToolCallResult(
                tool_calls=(NativeToolCall(id="c2", name="search", args={}),)
            ),
        ]
    )
    llm_call = _RecordingLlmCall('{"answer": "best-effort from gathered context"}')
    events = await _drive(adapter, llm_call, _config(max_tool_calls=1))

    assert not _errors(events), (
        "budget exhaustion must force-finalize, not raise an error"
    )
    finals = _final(events)
    assert finals, "expected a forced final event after the tool budget was exhausted"
    assert finals[-1].data.get("structured_output") is not None
    assert llm_call.calls, "the forced finalize must issue the Phase-2 structured call"
