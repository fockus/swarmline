"""react_strategy.py integration — Stage 3 stage-based soft masking (AGR-004).

Proves the FULL wiring (RuntimeConfig.native_config -> run_react -> ToolExecutor
-> stable_prefix.mask_tools): a tool masked out for this stage never actually
executes, while the tool-call SCHEMA sent to the native adapter stays exactly
the same as with no masking configured at all -- masking narrows which
ALREADY-pinned tool a turn may invoke, it never changes what the LLM is told
exists (Manus ``browser_``/``shell_`` pattern).
"""

from __future__ import annotations

import time

import pytest

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig, RuntimeEvent, ToolSpec


class _SequencedLlm:
    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)

    async def __call__(self, messages, prompt, **kwargs):
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


class _FakeNativeAdapter:
    """Records the tool_defs payload it was given, then plays back *results*."""

    def __init__(self, results: list[NativeToolCallResult]) -> None:
        self._results = list(results)
        self.received_tools: list[list[dict]] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.received_tools.append(list(tools))
        return self._results.pop(0)


def _native_config(**overrides) -> RuntimeConfig:
    base = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=4,
        max_tool_calls=8,
        use_native_tools=True,
    )
    base.update(overrides)
    return RuntimeConfig(**base)


_SHELL_TOOL = ToolSpec(
    name="shell_exec",
    description="run shell",
    parameters={"type": "object", "properties": {}},
)
_BROWSER_TOOL = ToolSpec(
    name="browser_click",
    description="click",
    parameters={"type": "object", "properties": {}},
)


async def _run_react_native_collect(
    llm, native_adapter, config, tools, executor
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in run_react(
        llm,
        executor,
        messages=[],
        system_prompt="You are a helpful assistant.",
        tools=tools,
        config=config,
        start_time=time.monotonic(),
        native_adapter=native_adapter,
    ):
        events.append(ev)
    return events


class TestReactStageMaskingWiring:
    @pytest.mark.asyncio
    async def test_masked_tool_never_executes_but_schema_is_unaffected(self) -> None:
        ran = False

        async def _spy_shell(**_):
            nonlocal ran
            ran = True
            return {"ok": True}

        executor = ToolExecutor(local_tools={"shell_exec": _spy_shell})
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="shell_exec", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(
            native_config={"stage_enabled_tool_names": ["browser_click"]}
        )

        await _run_react_native_collect(
            llm, adapter, config, [_SHELL_TOOL, _BROWSER_TOOL], executor
        )

        assert ran is False, "masked-out tool must never actually execute"
        # Schema stays exactly the same regardless of masking -- both tools are
        # still fully described to the model.
        schema_names = {t["name"] for t in adapter.received_tools[0]}
        assert schema_names == {"shell_exec", "browser_click"}

    @pytest.mark.asyncio
    async def test_no_stage_enabled_tool_names_is_a_no_op(self) -> None:
        """Default config (no native_config key at all) -> masking never engages."""
        ran = False

        async def _spy_shell(**_):
            nonlocal ran
            ran = True
            return {"ok": True}

        executor = ToolExecutor(local_tools={"shell_exec": _spy_shell})
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="shell_exec", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config()  # no stage_enabled_tool_names at all

        await _run_react_native_collect(
            llm, adapter, config, [_SHELL_TOOL, _BROWSER_TOOL], executor
        )

        assert ran is True, "no masking configured -> tool must execute normally"

    @pytest.mark.asyncio
    async def test_allowlist_cannot_enable_a_tool_outside_the_pinned_schema(
        self,
    ) -> None:
        """Fix-cycle 1 (M-2, codex round 1): ``stage_enabled_tool_names`` is an
        allowlist for tools ALREADY in the pinned schema -- it must be
        INTERSECTED with the pin, never trusted verbatim. Repro: the run's
        pinned tools are ``[alpha]`` only (``gamma`` is absent from BOTH the
        checkpoint snapshot and the tool_defs sent to the model), but the
        caller's allowlist explicitly names ``gamma``. Because ``ToolExecutor``
        dispatches by live-registry membership (not by the schema payload), a
        model that somehow still emits a ``gamma`` tool_call (hallucination,
        adversarial input, a stale client) must NOT have it actually run."""
        ran = False

        async def _spy_gamma(**_):
            nonlocal ran
            ran = True
            return {"ok": True}

        alpha_tool = ToolSpec(
            name="alpha",
            description="a",
            parameters={"type": "object", "properties": {}},
        )
        # gamma is registered/executable in the LIVE executor, but never part
        # of the pinned tool list passed to run_react() below.
        executor = ToolExecutor(local_tools={"alpha": _spy_gamma, "gamma": _spy_gamma})
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="gamma", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(native_config={"stage_enabled_tool_names": ["gamma"]})

        await _run_react_native_collect(llm, adapter, config, [alpha_tool], executor)

        assert ran is False, (
            "gamma is outside the pinned schema -- an explicit allowlist entry "
            "for it must NOT be enough to let it actually execute"
        )
        # And the schema sent to the model never mentioned gamma either.
        schema_names = {t["name"] for t in adapter.received_tools[0]}
        assert schema_names == {"alpha"}
