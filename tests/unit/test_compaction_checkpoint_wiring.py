"""Stage 6 (context-engineering-manus-parity) — compression_history checkpoint
persistence: runtime.py's compaction step loads/merges/writes it through the
SAME OSS-T4 checkpoint substrate (resilience/checkpoint.py) react_strategy.py's
own load-before-persist-block sites use, so it survives the M-1-class bug
(``CheckpointWriter.save_checkpoint`` fully REPLACES the stored dict on every
write -- a write that doesn't know about a key wipes it)."""

from __future__ import annotations

import json
import time

import pytest

from swarmline.compaction import (
    ANTI_THRASHING_WINDOW,
    CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY,
    CompactionConfig,
)
from swarmline.resilience.checkpoint import (
    CHECKPOINT_KEY_STEP,
    CHECKPOINT_KEY_TOTAL,
    CheckpointWriter,
    InMemoryCheckpointStore,
)
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.react_strategy import (
    CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD,
    CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS,
    CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT,
)
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec


class TestReservedKeyDoesNotCollide:
    """Team-lead guard: the new key must be distinct from every other
    reserved OSS-T4 checkpoint key."""

    def test_key_is_unique_among_all_reserved_keys(self) -> None:
        reserved = {
            CHECKPOINT_KEY_STEP,
            CHECKPOINT_KEY_TOTAL,
            CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT,
            CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD,
            CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS,
        }
        assert CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY not in reserved
        # Sanity: really are 6 distinct strings, not 5 + a duplicate.
        assert len({*reserved, CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY}) == 6


def _final_llm(text: str):
    async def _call(messages, system_prompt):
        return json.dumps({"type": "final", "final_message": text})

    return _call


class TestRuntimeCompactionStepPersistence:
    """runtime.py's compaction step: load prior compression_history, thread
    it through ConversationCompactionFilter, persist the (possibly
    unchanged) value back -- and react_strategy.py's OWN subsequent
    checkpoint writes (M-1 + per-tool-call) must round-trip it VERBATIM,
    never wipe it."""

    @pytest.mark.asyncio
    async def test_prior_compression_history_survives_a_full_run(self) -> None:
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-compaction-checkpoint-1"

        prior_history = [{"tokens_before": 1000, "tokens_after": 500}]
        await writer.after_tool_call(
            run_id=run_id,
            step=0,
            total_steps=4,
            state={CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: prior_history},
        )

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=8,
            compaction=CompactionConfig(threshold_tokens=100_000),  # never triggers
            checkpoint_writer=writer,
            run_id=run_id,
        )
        runtime = ThinRuntime(config=config, llm_call=_final_llm("hello"))
        events = [
            ev
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="sys",
                active_tools=[],
                config=config,
            )
        ]
        assert any(getattr(ev, "type", None) == "final" for ev in events)

        saved = await writer.load(run_id)
        assert saved is not None
        assert saved[CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY] == prior_history, (
            "compression_history was wiped by a later checkpoint write in the same run"
        )

    @pytest.mark.asyncio
    async def test_absent_prior_history_is_a_hard_no_op_empty_list(self) -> None:
        """First-ever run (nothing pre-seeded): the key still ends up
        persisted as an empty list, not absent -- so a LATER run reading it
        back gets a real (empty) list, never a KeyError/None surprise."""
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-compaction-checkpoint-2"

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=8,
            compaction=CompactionConfig(threshold_tokens=100_000),
            checkpoint_writer=writer,
            run_id=run_id,
        )
        runtime = ThinRuntime(config=config, llm_call=_final_llm("hello"))
        async for _ in runtime.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            config=config,
        ):
            pass

        saved = await writer.load(run_id)
        assert saved is not None
        assert saved[CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY] == []

    @pytest.mark.asyncio
    async def test_no_checkpoint_writer_is_byte_identical_no_op(self) -> None:
        """Absent checkpoint_writer/run_id: compaction still runs (filter is
        constructed with compression_history=[]), but nothing is persisted --
        no crash, no behavior change from before this wiring existed."""
        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=8,
            compaction=CompactionConfig(threshold_tokens=100_000),
        )
        runtime = ThinRuntime(config=config, llm_call=_final_llm("hello"))
        events = [
            ev
            async for ev in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="sys",
                active_tools=[],
                config=config,
            )
        ]
        assert any(getattr(ev, "type", None) == "final" for ev in events)


def _react_config(**overrides) -> RuntimeConfig:
    base = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=4,
        max_tool_calls=8,
    )
    base.update(overrides)
    return RuntimeConfig(**base)


def _final_response(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


class _SequencedLlm:
    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)

    async def __call__(self, messages, prompt, **kwargs):
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


class TestReactStrategyRoundTripsCompressionHistory:
    """Isolates the M-1-class bug at the react_strategy.py layer directly:
    a value ALREADY persisted (e.g. by runtime.py's compaction step, which
    runs before run_react() starts) must survive run_react()'s OWN
    unconditional M-1 + per-tool-call checkpoint writes byte-identically --
    this loop never reads OR modifies the value's meaning, only round-trips
    whatever runtime.py wrote."""

    @pytest.mark.asyncio
    async def test_preexisting_history_untouched_by_run_react(self) -> None:
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-react-compaction-history-1"
        seeded = [
            {"tokens_before": 2000, "tokens_after": 1900},
            {"tokens_before": 3000, "tokens_after": 2950},
        ]
        await writer.after_tool_call(
            run_id=run_id,
            step=0,
            total_steps=4,
            state={CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: seeded},
        )

        llm = _SequencedLlm([_final_response("done")])
        config = _react_config(checkpoint_writer=writer, run_id=run_id)
        async for _ in run_react(
            llm,
            ToolExecutor(local_tools={"dummy": lambda **_: '{"ok": true}'}),
            messages=[],
            system_prompt="sys",
            tools=[],
            config=config,
            start_time=time.monotonic(),
        ):
            pass

        saved = await writer.load(run_id)
        assert saved is not None
        assert saved[CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY] == seeded

    @pytest.mark.asyncio
    async def test_survives_a_tool_call_round_too(self) -> None:
        """Same proof, but exercising a real tool-call persist site (not
        just the M-1 immediate persist)."""
        store = InMemoryCheckpointStore()
        writer = CheckpointWriter(store, namespace="sw:")
        run_id = "run-react-compaction-history-2"
        seeded = [{"tokens_before": 500, "tokens_after": 480}]
        await writer.after_tool_call(
            run_id=run_id,
            step=0,
            total_steps=4,
            state={CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: seeded},
        )

        def _tool_response(name: str) -> str:
            return json.dumps(
                {
                    "type": "tool_call",
                    "tool": {"name": name, "args": {}, "correlation_id": "c1"},
                    "assistant_message": "",
                }
            )

        llm = _SequencedLlm([_tool_response("dummy"), _final_response("done")])
        config = _react_config(checkpoint_writer=writer, run_id=run_id)
        tool_spec = ToolSpec(
            name="dummy", description="d", parameters={"type": "object"}
        )
        async for _ in run_react(
            llm,
            ToolExecutor(local_tools={"dummy": lambda **_: '{"ok": true}'}),
            messages=[],
            system_prompt="sys",
            tools=[tool_spec],
            config=config,
            start_time=time.monotonic(),
        ):
            pass

        saved = await writer.load(run_id)
        assert saved is not None
        assert saved[CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY] == seeded


class TestAntiThrashingWindowConstant:
    def test_window_is_two(self) -> None:
        """Documents the exact ported constant from taskloom's
        conversation_distiller.py ANTI_THRASHING_WINDOW -- pinned so an
        accidental change is caught immediately."""
        assert ANTI_THRASHING_WINDOW == 2
