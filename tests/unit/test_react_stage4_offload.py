"""react_strategy.py integration -- Stage 4 tool-result offload (Filesystem as
context, context-engineering-manus-parity).

Proves the FULL wiring (RuntimeConfig.native_config -> run_react ->
resolve_tool_result_offload -> ScratchpadProvider): a large tool result is
written externally and replaced in the LLM-visible context by a restorable
projection, while staying fully readable back out via the scratchpad -- and
the frozen projection survives across two SEPARATE run_react() calls sharing
a run_id/checkpoint store (the same "two turns of the same run" proof
established for AGR-004 in Stage 3).
"""

from __future__ import annotations

import time

import pytest

from swarmline.resilience.checkpoint import CheckpointWriter, InMemoryCheckpointStore
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig, RuntimeEvent, ToolSpec
from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider


class _SequencedLlm:
    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)

    async def __call__(self, messages, prompt, **kwargs):
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


class _FakeNativeAdapter:
    """Records EVERY messages payload it was given, across every call."""

    def __init__(self, results: list[NativeToolCallResult]) -> None:
        self._results = list(results)
        self.received_messages: list[list[dict]] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.received_messages.append([dict(m) for m in messages])
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


_BIG_TOOL = ToolSpec(
    name="big_tool",
    description="returns a big result",
    parameters={"type": "object", "properties": {}},
)
_SCRATCH_READ_TOOL = ToolSpec(
    name="scratch_read",
    description="read a scratchpad entry by key",
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


def _joined_content(messages: list[dict]) -> str:
    return " ".join(
        m.get("content", "") for m in messages if isinstance(m.get("content"), str)
    )


class TestToolResultOffloadWiring:
    @pytest.mark.asyncio
    async def test_large_result_offloaded_and_restorable_via_scratchpad(self) -> None:
        # Well above both the 32k offload threshold AND the 120k per-result
        # ceiling (context_window_tokens=100_000, the minimum ENABLED window --
        # fix-cycle 1 MAJOR-5: offload is fully disabled below 100k) -- forces
        # REAL truncation, so the raw body must not survive verbatim in context.
        big_result = "B" * 200_000

        async def _big_tool(**_):
            return big_result

        executor = ToolExecutor(local_tools={"big_tool": _big_tool})
        provider = InMemoryScratchpadProvider()

        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            }
        )

        await _run_react_native_collect(
            llm, adapter, config, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor
        )

        assert len(adapter.received_messages) >= 2
        second_call_messages = adapter.received_messages[1]
        joined = _joined_content(second_call_messages)
        assert big_result not in joined
        assert "tool:call-1" in joined

        stored = await provider.read("tool:call-1")
        assert stored is not None
        assert stored.content == big_result

    @pytest.mark.asyncio
    async def test_short_result_is_never_offloaded(self) -> None:
        short_result = "ok"

        async def _small_tool(**_):
            return short_result

        executor = ToolExecutor(local_tools={"big_tool": _small_tool})
        provider = InMemoryScratchpadProvider()
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            }
        )

        await _run_react_native_collect(
            llm, adapter, config, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor
        )

        assert await provider.read("tool:call-1") is None

    @pytest.mark.asyncio
    async def test_no_scratchpad_provider_is_byte_identical_no_op(self) -> None:
        """Default config (no scratchpad_provider) -> large result untouched."""
        big_result = "B" * 40_000  # > 32k threshold, well below the 120k ceiling

        async def _big_tool(**_):
            return big_result

        executor = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config()  # no scratchpad_provider in native_config

        await _run_react_native_collect(
            llm, adapter, config, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor
        )

        second_call_messages = adapter.received_messages[1]
        assert big_result in _joined_content(second_call_messages)

    @pytest.mark.asyncio
    async def test_scratch_read_masked_out_skips_offload(self) -> None:
        """scratch_read IS in the pinned schema but masked out this stage ->
        restorability would be broken, so offload must not engage."""
        big_result = "B" * 40_000  # > 32k threshold, well below the 120k ceiling

        async def _big_tool(**_):
            return big_result

        executor = ToolExecutor(local_tools={"big_tool": _big_tool})
        provider = InMemoryScratchpadProvider()
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
                # scratch_read deliberately excluded from the stage allowlist.
                "stage_enabled_tool_names": ["big_tool"],
            }
        )

        await _run_react_native_collect(
            llm, adapter, config, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor
        )

        second_call_messages = adapter.received_messages[1]
        assert big_result in _joined_content(second_call_messages)
        assert await provider.read("tool:call-1") is None

    @pytest.mark.asyncio
    async def test_scratch_read_absent_from_pinned_tools_skips_offload(self) -> None:
        """scratch_read is not even part of THIS run's tool schema at all."""
        big_result = "B" * 40_000  # > 32k threshold, well below the 120k ceiling

        async def _big_tool(**_):
            return big_result

        executor = ToolExecutor(local_tools={"big_tool": _big_tool})
        provider = InMemoryScratchpadProvider()
        adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            }
        )

        # NOTE: tools list does NOT include _SCRATCH_READ_TOOL at all.
        await _run_react_native_collect(llm, adapter, config, [_BIG_TOOL], executor)

        second_call_messages = adapter.received_messages[1]
        assert big_result in _joined_content(second_call_messages)
        assert await provider.read("tool:call-1") is None


class TestToolResultOffloadFrozenAcrossRuns:
    @pytest.mark.asyncio
    async def test_frozen_projection_byte_identical_across_two_run_react_calls(
        self,
    ) -> None:
        """Two SEPARATE run_react() calls sharing a run_id/checkpoint store:
        the SECOND call must reuse the FIRST call's exact frozen projection,
        never recomputing it from a (possibly different) fresh result."""
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        provider = InMemoryScratchpadProvider()
        big_result = "B" * 40_000  # > 32k threshold, well below the 120k ceiling

        async def _big_tool(**_):
            return big_result

        # --- Turn 1: a tool call that triggers the offload.
        executor_1 = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_1 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm_1 = _SequencedLlm(['{"answer": "ok"}'])
        config_1 = _native_config(
            checkpoint_writer=writer,
            run_id="run-offload-1",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_1, adapter_1, config_1, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_1
        )
        first_call_context = _joined_content(adapter_1.received_messages[1])
        assert "tool:call-1" in first_call_context

        # --- Turn 2: a SEPARATE run_react() call (fresh executor/adapter, same
        # run_id/store/scratchpad) -- simulates a later HTTP request. The tool
        # call is never re-issued (no fresh native tool_calls this turn), so
        # the ONLY way the projection could resurface is via the frozen
        # checkpoint state persisted by turn 1 (there's no in-process state
        # carried between these two independent run_react() invocations).
        executor_2 = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_2 = _FakeNativeAdapter(
            [NativeToolCallResult(text="done2", tool_calls=())]
        )
        llm_2 = _SequencedLlm(['{"answer": "ok2"}'])
        config_2 = _native_config(
            checkpoint_writer=writer,
            run_id="run-offload-1",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_2, adapter_2, config_2, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_2
        )

        saved = await writer.load("run-offload-1")
        assert saved is not None
        from swarmline.runtime.thin.tool_result_offload import (
            CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD,
        )

        restored_projections = saved[CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD]
        assert "call-1" in restored_projections
        # The persisted projection is EXACTLY the text turn 1 put in context --
        # confirming persist and in-context text are the same value, not two
        # independently-computed copies that merely happen to look similar.
        assert restored_projections["call-1"] in first_call_context


class TestStickyScratchReadAfterOffload:
    """Fix-cycle 1 (CRITICAL-3b / "Variant A", codex round 1): once an offload
    has happened anywhere in a run, scratch_read must stay callable for the
    rest of the run, even if a LATER turn's stage_enabled_tool_names masks it
    out -- otherwise a projection frozen while scratch_read WAS available
    could become permanently unrestorable."""

    @pytest.mark.asyncio
    async def test_scratch_read_stays_callable_after_offload_even_if_masked_later(
        self,
    ) -> None:
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        provider = InMemoryScratchpadProvider()
        big_result = "B" * 200_000

        async def _big_tool(**_):
            return big_result

        # --- T1: an offload happens (freezes a projection for call-1).
        executor_1 = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_1 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm_1 = _SequencedLlm(['{"answer": "ok"}'])
        config_1 = _native_config(
            checkpoint_writer=writer,
            run_id="run-sticky",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_1, adapter_1, config_1, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_1
        )

        # --- T2: SEPARATE run_react() call, SAME run_id -- this stage's
        # allowlist deliberately EXCLUDES scratch_read. The sticky invariant
        # must override that, since T1 already froze an offload projection.
        ran_scratch_read = False

        async def _scratch_read_spy(**_):
            nonlocal ran_scratch_read
            ran_scratch_read = True
            return {"ok": True}

        executor_2 = ToolExecutor(
            local_tools={"big_tool": _big_tool, "scratch_read": _scratch_read_spy}
        )
        adapter_2 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(
                        NativeToolCall(
                            id="call-2",
                            name="scratch_read",
                            args={"key": "tool:call-1"},
                        ),
                    )
                ),
                NativeToolCallResult(text="done2", tool_calls=()),
            ]
        )
        llm_2 = _SequencedLlm(['{"answer": "ok2"}'])
        config_2 = _native_config(
            checkpoint_writer=writer,
            run_id="run-sticky",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
                # scratch_read deliberately excluded from THIS stage's allowlist.
                "stage_enabled_tool_names": ["big_tool"],
            },
        )
        await _run_react_native_collect(
            llm_2, adapter_2, config_2, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_2
        )

        assert ran_scratch_read is True, (
            "scratch_read must stay callable for the rest of the run once an "
            "offload has happened, even if a later stage masks it out"
        )

    @pytest.mark.asyncio
    async def test_write_failure_fallback_only_does_not_trigger_sticky_reenable(
        self,
    ) -> None:
        """Fix-cycle 2 (3b, codex round 2): a run whose ONLY frozen state is a
        write-failure fallback (ZERO successful offloads) must NOT trigger the
        sticky scratch_read re-add -- masking stays byte-identical, because
        there is no scratch key to restore in the first place."""
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")

        class _FailingProvider:
            async def write(self, key: str, content: str, tags: tuple = ()) -> None:
                raise OSError("disk full")

        big_result = "B" * 200_000

        async def _big_tool(**_):
            return big_result

        # --- T1: offload is ATTEMPTED but the scratchpad write FAILS -- only
        # a full-body fallback gets frozen, no successful projection.
        executor_1 = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_1 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm_1 = _SequencedLlm(['{"answer": "ok"}'])
        config_1 = _native_config(
            checkpoint_writer=writer,
            run_id="run-fallback-only",
            native_config={
                "scratchpad_provider": _FailingProvider(),
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_1, adapter_1, config_1, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_1
        )

        # --- T2: SAME run_id, allowlist excludes scratch_read. Since T1 never
        # SUCCEEDED at offloading, the sticky re-add must stay OFF.
        ran_scratch_read = False

        async def _scratch_read_spy(**_):
            nonlocal ran_scratch_read
            ran_scratch_read = True
            return {"ok": True}

        executor_2 = ToolExecutor(
            local_tools={"big_tool": _big_tool, "scratch_read": _scratch_read_spy}
        )
        adapter_2 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(
                        NativeToolCall(
                            id="call-2",
                            name="scratch_read",
                            args={"key": "tool:call-1"},
                        ),
                    )
                ),
                NativeToolCallResult(text="done2", tool_calls=()),
            ]
        )
        llm_2 = _SequencedLlm(['{"answer": "ok2"}'])
        config_2 = _native_config(
            checkpoint_writer=writer,
            run_id="run-fallback-only",
            native_config={
                "scratchpad_provider": _FailingProvider(),
                "context_window_tokens": 100_000,
                "stage_enabled_tool_names": ["big_tool"],  # scratch_read excluded
            },
        )
        await _run_react_native_collect(
            llm_2, adapter_2, config_2, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_2
        )

        assert ran_scratch_read is False, (
            "scratch_read must stay MASKED when the only frozen state is a "
            "write-failure fallback -- never a successful offload"
        )


# ---------------------------------------------------------------------------
# Text-ReAct path -- same wiring, different call site (JSON-in-text tool_call)
# ---------------------------------------------------------------------------


class _TextReActLlm:
    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)
        self.received_messages: list[list[dict]] = []

    async def __call__(self, messages, prompt, **kwargs):
        self.received_messages.append([dict(m) for m in messages])
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


def _tool_response(name: str, args: dict | None = None) -> str:
    import json

    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args or {}, "correlation_id": "call-1"},
            "assistant_message": "",
        }
    )


def _final_response(text: str) -> str:
    import json

    return json.dumps({"type": "final", "final_message": text})


class TestToolResultOffloadWiring_TextReActPath:
    @pytest.mark.asyncio
    async def test_large_result_offloaded_in_text_react_path_too(self) -> None:
        """The SAME resolve_tool_result_offload() call site wired into the
        text-ReAct (JSON-in-text tool_call) branch, not only the native path."""
        big_result = "T" * 200_000

        async def _big_tool(**_):
            return big_result

        executor = ToolExecutor(local_tools={"big_tool": _big_tool})
        provider = InMemoryScratchpadProvider()
        llm = _TextReActLlm([_tool_response("big_tool"), _final_response("done")])
        config = _native_config(
            use_native_tools=False,
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )

        events: list[RuntimeEvent] = []
        async for ev in run_react(
            llm,
            executor,
            messages=[],
            system_prompt="You are a helpful assistant.",
            tools=[_BIG_TOOL, _SCRATCH_READ_TOOL],
            config=config,
            start_time=time.monotonic(),
        ):
            events.append(ev)

        assert len(llm.received_messages) >= 2
        second_call_context = _joined_content(llm.received_messages[1])
        assert big_result not in second_call_context
        assert "tool:call-1" in second_call_context

        stored = await provider.read("tool:call-1")
        assert stored is not None
        assert stored.content == big_result


class TestFrozenOffloadSurvivesToolCallFreeTurn:
    """(#1, codex round 1 pre-staged focus area): the M-1-class ordering bug
    from Stage 3, now checked for Stage 4's own frozen state -- a turn that
    makes ZERO tool calls at all must NOT wipe a PRIOR turn's frozen offload
    projections (the self-caught fix: loading _frozen_offload_projections
    from the checkpoint BEFORE the M-1 unconditional persist block, not after)."""

    @pytest.mark.asyncio
    async def test_round_trip_freeze_then_tool_call_free_turn_then_verbatim_reuse(
        self,
    ) -> None:
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        provider = InMemoryScratchpadProvider()
        big_result = "B" * 200_000

        async def _big_tool(**_):
            return big_result

        from swarmline.runtime.thin.tool_result_offload import (
            CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD,
        )

        # --- T: a tool call that triggers the offload; call-1 gets frozen.
        executor_t = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_t = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm_t = _SequencedLlm(['{"answer": "t"}'])
        config_t = _native_config(
            checkpoint_writer=writer,
            run_id="run-roundtrip",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_t, adapter_t, config_t, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_t
        )
        saved_t = await writer.load("run-roundtrip")
        assert saved_t is not None
        frozen_t = saved_t[CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD]
        assert "call-1" in frozen_t
        projection_t = frozen_t["call-1"]

        # --- T+1: a SEPARATE run_react() call, SAME run_id, ZERO tool calls
        # at all this turn (immediate final answer). This is exactly the
        # shape of turn that, without the self-caught ordering fix, would let
        # the M-1 unconditional persist blindly overwrite the checkpoint state
        # with an EMPTY offload map.
        executor_t1 = ToolExecutor(local_tools={"big_tool": _big_tool})
        adapter_t1 = _FakeNativeAdapter(
            [NativeToolCallResult(text="no tools this turn at all", tool_calls=())]
        )
        llm_t1 = _SequencedLlm(['{"answer": "t1"}'])
        config_t1 = _native_config(
            checkpoint_writer=writer,
            run_id="run-roundtrip",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_t1, adapter_t1, config_t1, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_t1
        )

        saved_t1 = await writer.load("run-roundtrip")
        assert saved_t1 is not None
        frozen_t1 = saved_t1[CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD]
        assert frozen_t1 == frozen_t, (
            "a tool-call-free turn must NEVER wipe a prior turn's frozen "
            f"offload state -- before: {frozen_t!r}, after: {frozen_t1!r}"
        )

        # --- T+2: a THIRD run_react() call, SAME run_id, call-1 is "re-issued"
        # with a COMPLETELY DIFFERENT underlying result. If the freeze truly
        # survived T+1 untouched, T+2 must show the ORIGINAL (T's) projection
        # verbatim, never the new body.
        async def _big_tool_different(**_):
            return "COMPLETELY_DIFFERENT_BODY_" * 20_000

        executor_t2 = ToolExecutor(local_tools={"big_tool": _big_tool_different})
        adapter_t2 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="call-1", name="big_tool", args={}),)
                ),
                NativeToolCallResult(text="done-t2", tool_calls=()),
            ]
        )
        llm_t2 = _SequencedLlm(['{"answer": "t2"}'])
        config_t2 = _native_config(
            checkpoint_writer=writer,
            run_id="run-roundtrip",
            native_config={
                "scratchpad_provider": provider,
                "context_window_tokens": 100_000,
            },
        )
        await _run_react_native_collect(
            llm_t2, adapter_t2, config_t2, [_BIG_TOOL, _SCRATCH_READ_TOOL], executor_t2
        )

        t2_context = _joined_content(adapter_t2.received_messages[1])
        assert projection_t in t2_context
        assert "COMPLETELY_DIFFERENT_BODY_" not in t2_context
