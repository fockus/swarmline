"""OSS-T4 — Durable execution: checkpoint + recovery + stream-chunk.

Covers REQ-OSS-020 (checkpoint per tool-call, resume on restart) and
REQ-OSS-021 (recovery strategy dispatch: RETRY/SKIP/ROLLBACK/MANUAL).

TDD: all tests written BEFORE the implementation.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from swarmline.resilience.checkpoint import (
    CHECKPOINT_KEY_STEP,
    CHECKPOINT_KEY_TOTAL,
    Checkpoint,
    CheckpointWriter,
    CrashRecoveryService,
    InMemoryCheckpointStore,
    RecoveryStrategy,
    RunStreamChunk,
)
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.react_strategy import _read_lm_messages
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig, RuntimeEvent, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> InMemoryCheckpointStore:
    return InMemoryCheckpointStore()


def _make_writer(
    store: InMemoryCheckpointStore | None = None,
    *,
    namespace: str = "sw:",
) -> CheckpointWriter:
    if store is None:
        store = _make_store()
    return CheckpointWriter(store, namespace=namespace)


def _frozen_clock(ts: datetime):
    def _clock() -> datetime:
        return ts

    return _clock


# ---------------------------------------------------------------------------
# InMemoryCheckpointStore
# ---------------------------------------------------------------------------


class TestInMemoryCheckpointStore:
    """Unit tests for the in-memory reference implementation of CheckpointPort."""

    def test_save_and_load_returns_state(self) -> None:
        """load_checkpoint returns exactly the dict that was saved."""
        store = _make_store()
        state: dict[str, Any] = {"key": "value", "n": 42}
        store.save_checkpoint("run-1", state)
        loaded = store.load_checkpoint("run-1")
        assert loaded == state

    def test_load_missing_run_returns_none(self) -> None:
        """load_checkpoint returns None for an unknown run_id."""
        store = _make_store()
        assert store.load_checkpoint("ghost") is None

    def test_save_overwrites_previous(self) -> None:
        """Repeated saves overwrite the previous checkpoint."""
        store = _make_store()
        store.save_checkpoint("run-1", {"step": 1})
        store.save_checkpoint("run-1", {"step": 2})
        loaded = store.load_checkpoint("run-1")
        assert loaded == {"step": 2}

    def test_clear_removes_entry(self) -> None:
        """clear_checkpoint removes the run_id from the store."""
        store = _make_store()
        store.save_checkpoint("run-1", {"x": 1})
        store.clear_checkpoint("run-1")
        assert store.load_checkpoint("run-1") is None

    def test_clear_nonexistent_is_noop(self) -> None:
        """Clearing a non-existent key does not raise."""
        store = _make_store()
        store.clear_checkpoint("no-such-run")  # must not raise

    def test_list_orphaned_returns_all_saved_run_ids(self) -> None:
        """list_orphaned returns all run_ids currently saved."""
        store = _make_store()
        store.save_checkpoint("run-a", {"x": 1})
        store.save_checkpoint("run-b", {"y": 2})
        orphaned = store.list_orphaned()
        assert set(orphaned) == {"run-a", "run-b"}

    def test_list_orphaned_empty_when_nothing_saved(self) -> None:
        """list_orphaned returns an empty list when the store is empty."""
        store = _make_store()
        assert store.list_orphaned() == []

    def test_list_orphaned_excludes_cleared_run_ids(self) -> None:
        """After clear, run_id no longer appears in list_orphaned."""
        store = _make_store()
        store.save_checkpoint("run-a", {})
        store.save_checkpoint("run-b", {})
        store.clear_checkpoint("run-a")
        assert store.list_orphaned() == ["run-b"]

    def test_satisfies_checkpoint_port_protocol(self) -> None:
        """InMemoryCheckpointStore must structurally satisfy CheckpointPort."""

        # CheckpointPort is a Protocol; just verify all four methods are present.
        store = _make_store()
        assert callable(store.save_checkpoint)
        assert callable(store.load_checkpoint)
        assert callable(store.clear_checkpoint)
        assert callable(store.list_orphaned)


# ---------------------------------------------------------------------------
# CheckpointWriter — after_tool_call, on_run_complete, namespace
# ---------------------------------------------------------------------------


class TestCheckpointWriter:
    """CheckpointWriter persists namespaced checkpoints after tool calls."""

    @pytest.mark.asyncio
    async def test_after_tool_call_persists_with_reserved_keys(self) -> None:
        """after_tool_call injects _step and _total_steps into the saved state."""
        store = _make_store()
        writer = _make_writer(store)
        await writer.after_tool_call(
            run_id="r1", step=3, total_steps=10, state={"ctx": "abc"}
        )
        saved = store.load_checkpoint("sw:r1")
        assert saved is not None
        assert saved[CHECKPOINT_KEY_STEP] == 3
        assert saved[CHECKPOINT_KEY_TOTAL] == 10
        assert saved["ctx"] == "abc"  # caller's keys are untouched

    @pytest.mark.asyncio
    async def test_after_tool_call_does_not_mutate_input_state(self) -> None:
        """after_tool_call must not mutate the caller's state dict."""
        store = _make_store()
        writer = _make_writer(store)
        original: dict[str, Any] = {"k": "v"}
        snapshot = dict(original)
        await writer.after_tool_call(run_id="r1", step=1, total_steps=5, state=original)
        assert original == snapshot

    @pytest.mark.asyncio
    async def test_multiple_writes_keep_latest(self) -> None:
        """Repeated after_tool_call calls overwrite; load returns the latest."""
        store = _make_store()
        writer = _make_writer(store)
        for step in range(1, 6):
            await writer.after_tool_call(
                run_id="r1", step=step, total_steps=10, state={"step_val": step}
            )
        saved = store.load_checkpoint("sw:r1")
        assert saved is not None
        assert saved[CHECKPOINT_KEY_STEP] == 5
        assert saved["step_val"] == 5

    @pytest.mark.asyncio
    async def test_on_run_complete_clears_checkpoint(self) -> None:
        """on_run_complete clears the namespaced key for the run."""
        store = _make_store()
        writer = _make_writer(store)
        await writer.after_tool_call(run_id="r1", step=2, total_steps=5, state={})
        await writer.on_run_complete(run_id="r1")
        assert store.load_checkpoint("sw:r1") is None

    @pytest.mark.asyncio
    async def test_namespace_prefix_isolates_keys(self) -> None:
        """Different namespace prefixes write to different keys in the same store."""
        store = _make_store()
        writer_a = CheckpointWriter(store, namespace="ns-a:")
        writer_b = CheckpointWriter(store, namespace="ns-b:")
        await writer_a.after_tool_call(
            run_id="r1", step=1, total_steps=5, state={"from": "a"}
        )
        await writer_b.after_tool_call(
            run_id="r1", step=2, total_steps=5, state={"from": "b"}
        )
        # Each writer's key is independent
        loaded_a = store.load_checkpoint("ns-a:r1")
        loaded_b = store.load_checkpoint("ns-b:r1")
        assert loaded_a is not None and loaded_a["from"] == "a"
        assert loaded_b is not None and loaded_b["from"] == "b"

    @pytest.mark.asyncio
    async def test_load_returns_none_before_any_write(self) -> None:
        """load returns None when no checkpoint has been written for run_id."""
        store = _make_store()
        writer = _make_writer(store)
        result = await writer.load("r1")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_returns_saved_state(self) -> None:
        """load returns the state previously saved by after_tool_call."""
        store = _make_store()
        writer = _make_writer(store)
        await writer.after_tool_call(
            run_id="r1", step=3, total_steps=7, state={"x": 99}
        )
        result = await writer.load("r1")
        assert result is not None
        assert result["x"] == 99
        assert result[CHECKPOINT_KEY_STEP] == 3


# ---------------------------------------------------------------------------
# CrashRecoveryService — create / get_latest / recover / cleanup
# ---------------------------------------------------------------------------


class TestCrashRecoveryService:
    """CrashRecoveryService manages Checkpoint lifecycle and recovery dispatch."""

    def test_create_checkpoint_returns_frozen_dataclass(self) -> None:
        """create_checkpoint returns a frozen Checkpoint with correct fields."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        svc = CrashRecoveryService(clock=_frozen_clock(ts))
        cp = svc.create_checkpoint("run-1", step_index=2, state={"k": "v"})
        assert isinstance(cp, Checkpoint)
        assert cp.run_id == "run-1"
        assert cp.step_index == 2
        assert cp.state == {"k": "v"}
        assert cp.created_at == ts

    def test_get_latest_returns_max_step_index(self) -> None:
        """get_latest_checkpoint returns the one with the highest step_index."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=1, state={})
        svc.create_checkpoint("run-1", step_index=3, state={})
        svc.create_checkpoint("run-1", step_index=2, state={})
        latest = svc.get_latest_checkpoint("run-1")
        assert latest is not None
        assert latest.step_index == 3

    def test_get_latest_returns_none_for_unknown_run(self) -> None:
        """get_latest_checkpoint returns None when no checkpoints exist."""
        svc = CrashRecoveryService()
        assert svc.get_latest_checkpoint("ghost") is None

    def test_recover_retry_dispatches_distinct_branch(self) -> None:
        """recover(RETRY) returns a message referencing 'retry'."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=3, state={})
        result = svc.recover("run-1", RecoveryStrategy.RETRY)
        assert "retry" in result.lower()
        assert "step=3" in result

    def test_recover_skip_dispatches_distinct_branch(self) -> None:
        """recover(SKIP) returns a message referencing 'skip'."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=4, state={})
        result = svc.recover("run-1", RecoveryStrategy.SKIP)
        assert "skip" in result.lower()
        assert "step=4" in result

    def test_recover_rollback_dispatches_distinct_branch(self) -> None:
        """recover(ROLLBACK) returns a message referencing 'rollback'."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=5, state={})
        result = svc.recover("run-1", RecoveryStrategy.ROLLBACK)
        assert "rollback" in result.lower()
        assert "step=5" in result

    def test_recover_manual_dispatches_distinct_branch(self) -> None:
        """recover(MANUAL) returns a message referencing 'manual'."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=6, state={})
        result = svc.recover("run-1", RecoveryStrategy.MANUAL)
        assert "manual" in result.lower()

    def test_all_four_strategies_produce_distinct_messages(self) -> None:
        """Each RecoveryStrategy branch produces a distinct output string."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-x", step_index=7, state={})
        results = {s: svc.recover("run-x", s) for s in RecoveryStrategy}
        # All distinct
        assert len(set(results.values())) == 4

    def test_recover_no_checkpoint_reports_no_checkpoint(self) -> None:
        """recover on a run with no checkpoint still returns a string (no crash)."""
        svc = CrashRecoveryService()
        result = svc.recover("no-such-run", RecoveryStrategy.RETRY)
        assert isinstance(result, str)
        assert "no checkpoint" in result

    def test_cleanup_removes_all_checkpoints_and_returns_count(self) -> None:
        """cleanup_checkpoints removes all entries and returns the deleted count."""
        svc = CrashRecoveryService()
        svc.create_checkpoint("run-1", step_index=1, state={})
        svc.create_checkpoint("run-1", step_index=2, state={})
        count = svc.cleanup_checkpoints("run-1")
        assert count == 2
        assert svc.get_latest_checkpoint("run-1") is None

    def test_cleanup_nonexistent_returns_zero(self) -> None:
        """cleanup_checkpoints on an unknown run_id returns 0 without raising."""
        svc = CrashRecoveryService()
        assert svc.cleanup_checkpoints("ghost") == 0

    def test_default_clock_is_utc_aware(self) -> None:
        """When no clock is injected, created_at is a UTC-aware datetime."""
        svc = CrashRecoveryService()
        cp = svc.create_checkpoint("run-1", step_index=0, state={})
        assert cp.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# RunStreamChunk discriminated union
# ---------------------------------------------------------------------------


class TestRunStreamChunk:
    """RunStreamChunk discriminated union over kind='tool'|'final'."""

    def test_tool_chunk_is_tool_true(self) -> None:
        """A chunk with kind='tool' has is_tool=True, is_final=False."""
        chunk = RunStreamChunk(
            kind="tool", tool_name="search", tool_result='{"results": []}'
        )
        assert chunk.is_tool is True
        assert chunk.is_final is False

    def test_final_chunk_is_final_true(self) -> None:
        """A chunk with kind='final' has is_final=True, is_tool=False."""
        chunk = RunStreamChunk(kind="final", final_text="All done.")
        assert chunk.is_final is True
        assert chunk.is_tool is False

    def test_chunk_is_frozen(self) -> None:
        """RunStreamChunk instances are immutable (frozen dataclass)."""
        chunk = RunStreamChunk(kind="final", final_text="x")
        with pytest.raises((AttributeError, TypeError)):
            chunk.final_text = "y"  # type: ignore[misc]

    def test_tool_chunk_carries_name_and_result(self) -> None:
        """Tool chunks carry the tool name and result payload."""
        chunk = RunStreamChunk(kind="tool", tool_name="calc", tool_result="42")
        assert chunk.tool_name == "calc"
        assert chunk.tool_result == "42"

    def test_final_chunk_carries_text(self) -> None:
        """Final chunks carry the final_text payload."""
        chunk = RunStreamChunk(kind="final", final_text="Answer is 42.")
        assert chunk.final_text == "Answer is 42."

    def test_kind_field_present_on_both(self) -> None:
        """The kind discriminator field is accessible on both chunk types."""
        tool_chunk = RunStreamChunk(kind="tool", tool_name="t", tool_result="r")
        final_chunk = RunStreamChunk(kind="final", final_text="f")
        assert tool_chunk.kind == "tool"
        assert final_chunk.kind == "final"


# ---------------------------------------------------------------------------
# React loop — byte-identical regression + checkpoint wiring
# ---------------------------------------------------------------------------


def _react_config(**overrides) -> RuntimeConfig:
    """Minimal RuntimeConfig for text-ReAct tests."""
    base = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=4,
        max_tool_calls=8,
    )
    base.update(overrides)
    return RuntimeConfig(**base)


class _SequencedLlm:
    """Mock LLM: returns responses from the queue (last repeats)."""

    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)
        self.calls: int = 0

    async def __call__(self, messages, prompt, **kwargs):
        self.calls += 1
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


class _RecordingLlm:
    """Mock LLM: records every message array it receives + sequences responses."""

    def __init__(self, raws: list[str]) -> None:
        self._raws = list(raws)
        self.received_messages: list[list[dict]] = []

    async def __call__(self, messages, prompt, **kwargs):
        self.received_messages.append(list(messages))
        return self._raws.pop(0) if len(self._raws) > 1 else self._raws[-1]


def _tool_response(name: str, args: dict | None = None) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args or {}, "correlation_id": "c1"},
            "assistant_message": "",
        }
    )


def _final_response(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


async def _run_react_collect(
    llm: _SequencedLlm,
    config: RuntimeConfig,
    tools: list[ToolSpec] | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in run_react(
        llm,
        ToolExecutor(local_tools={"dummy": lambda **_: '{"ok": true}'}),
        messages=[],
        system_prompt="You are a helpful assistant.",
        tools=tools or [],
        config=config,
        start_time=time.monotonic(),
    ):
        events.append(ev)
    return events


class TestReactByteIdenticalRegression:
    """With no checkpoint_writer, the react loop emits exactly the same events."""

    @pytest.mark.asyncio
    async def test_no_checkpoint_writer_no_resume_status(self) -> None:
        """Default config (checkpoint_writer=None) emits no 'resumed' status event."""
        llm = _SequencedLlm([_final_response("hello")])
        config = _react_config()
        events = await _run_react_collect(llm, config)
        statuses = [
            e.data.get("text", "") if isinstance(e.data, dict) else str(e.data)
            for e in events
            if getattr(e, "type", None) == "status"
        ]
        assert not any("resumed" in s for s in statuses)

    @pytest.mark.asyncio
    async def test_no_checkpoint_writer_final_event_present(self) -> None:
        """Default config still produces a final event (loop not broken)."""
        llm = _SequencedLlm([_final_response("result")])
        config = _react_config()
        events = await _run_react_collect(llm, config)
        types = [getattr(e, "type", None) for e in events]
        assert "final" in types

    @pytest.mark.asyncio
    async def test_no_checkpoint_writer_tool_cycle_unchanged(self) -> None:
        """Tool call + final cycle with no checkpoint_writer works as before."""
        tool_spec = ToolSpec(
            name="dummy",
            description="dummy tool",
            parameters={"type": "object", "properties": {}},
        )
        llm = _SequencedLlm([_tool_response("dummy"), _final_response("done")])
        config = _react_config()
        events = await _run_react_collect(llm, config, tools=[tool_spec])
        types = [getattr(e, "type", None) for e in events]
        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types


class TestReactCheckpointWiring:
    """With checkpoint_writer wired, resume notice is emitted and writes happen."""

    @pytest.mark.asyncio
    async def test_resume_notice_emitted_when_checkpoint_exists(self) -> None:
        """A status event 'resumed from checkpoint step N/M' is emitted on start."""
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")
        # Pre-populate: simulate a previous run that saved step 2 of 5.
        store.save_checkpoint(
            "sw:run-42", {CHECKPOINT_KEY_STEP: 2, CHECKPOINT_KEY_TOTAL: 5}
        )

        llm = _SequencedLlm([_final_response("continued")])
        config = _react_config(checkpoint_writer=writer, run_id="run-42")
        events = await _run_react_collect(llm, config)

        status_messages = [
            e.data.get("text", "") if isinstance(e.data, dict) else str(e.data)
            for e in events
            if getattr(e, "type", None) == "status"
        ]
        assert any("resumed" in m and "2" in m and "5" in m for m in status_messages), (
            f"Expected 'resumed from checkpoint step 2/5' in statuses, got: {status_messages}"
        )

    @pytest.mark.asyncio
    async def test_no_resume_when_no_prior_checkpoint(self) -> None:
        """If checkpoint_writer is set but no prior checkpoint, no resume notice."""
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")

        llm = _SequencedLlm([_final_response("fresh run")])
        config = _react_config(checkpoint_writer=writer, run_id="run-99")
        events = await _run_react_collect(llm, config)

        status_messages = [
            e.data.get("text", "") if isinstance(e.data, dict) else str(e.data)
            for e in events
            if getattr(e, "type", None) == "status"
        ]
        assert not any("resumed" in m for m in status_messages)

    @pytest.mark.asyncio
    async def test_checkpoint_written_after_tool_call(self) -> None:
        """A checkpoint is persisted in the store after each tool call completes."""
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")
        tool_spec = ToolSpec(
            name="dummy",
            description="dummy",
            parameters={"type": "object", "properties": {}},
        )
        llm = _SequencedLlm([_tool_response("dummy"), _final_response("done")])
        config = _react_config(
            checkpoint_writer=writer, run_id="run-77", max_iterations=4
        )
        await _run_react_collect(llm, config, tools=[tool_spec])

        # After tool call completes, a checkpoint should be saved.
        saved = store.load_checkpoint("sw:run-77")
        assert saved is not None, "Expected a checkpoint to be written after tool call"
        assert CHECKPOINT_KEY_STEP in saved


# ---------------------------------------------------------------------------
# React native-tools path — checkpoint wiring (REQ-OSS-020 completeness)
# ---------------------------------------------------------------------------


class _FakeNativeAdapter:
    """Minimal fake: returns a configured sequence of NativeToolCallResult."""

    def __init__(self, results: list[NativeToolCallResult]) -> None:
        self._results = list(results)
        self.call_count: int = 0
        # Stage 3 (AGR-004): records the exact tool_defs payload react_strategy.py
        # built for every call_with_tools() invocation -- used to assert the
        # pinned-schema invariant (byte-identical across turns of the same run).
        self.received_tools: list[list[dict]] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.call_count += 1
        self.received_tools.append(list(tools))
        assert self._results, "fake native adapter called more times than seeded"
        return self._results.pop(0)


def _native_config(**overrides) -> RuntimeConfig:
    """RuntimeConfig with native tools enabled."""
    base = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        max_iterations=4,
        max_tool_calls=8,
        use_native_tools=True,
    )
    base.update(overrides)
    return RuntimeConfig(**base)


async def _run_react_native_collect(
    llm,
    native_adapter: _FakeNativeAdapter,
    config: RuntimeConfig,
    tools: list[ToolSpec] | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in run_react(
        llm,
        ToolExecutor(local_tools={"dummy": lambda **_: '{"ok": true}'}),
        messages=[],
        system_prompt="You are a helpful assistant.",
        tools=tools
        or [
            ToolSpec(
                name="dummy",
                description="d",
                parameters={"type": "object", "properties": {}},
            )
        ],
        config=config,
        start_time=time.monotonic(),
        native_adapter=native_adapter,
    ):
        events.append(ev)
    return events


class TestReactNativePathCheckpointWiring:
    """REQ-OSS-020: checkpoint must be written after native-tools tool calls too."""

    @pytest.mark.asyncio
    async def test_checkpoint_written_after_native_tool_call(self) -> None:
        """A checkpoint is saved in the store after a native-path tool call."""
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")

        # Phase 1: one tool call turn.
        # Phase 2: finalize (no more tool calls) → run ends.
        native_adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="dummy", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config(checkpoint_writer=writer, run_id="native-run-1")
        await _run_react_native_collect(llm, native_adapter, config)

        saved = store.load_checkpoint("sw:native-run-1")
        assert saved is not None, (
            "Expected checkpoint after native tool call — none found"
        )
        assert CHECKPOINT_KEY_STEP in saved, (
            f"Expected {CHECKPOINT_KEY_STEP!r} in saved checkpoint, got: {saved}"
        )

    @pytest.mark.asyncio
    async def test_no_checkpoint_on_native_path_when_writer_absent(self) -> None:
        """Default config (checkpoint_writer=None) writes nothing on native path."""
        store = _make_store()

        native_adapter = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="dummy", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm = _SequencedLlm(['{"answer": "ok"}'])
        config = _native_config()  # no checkpoint_writer
        await _run_react_native_collect(llm, native_adapter, config)

        # Store must remain empty — default path unchanged.
        assert store.list_orphaned() == []


# ---------------------------------------------------------------------------
# Full-state resume regression — REQ-OSS-020 correctness
# ---------------------------------------------------------------------------


class TestReactCheckpointFullStateResume:
    """Resume must restore lm_messages, not only the iteration counter."""

    @pytest.mark.asyncio
    async def test_resume_restores_conversation_context(self) -> None:
        """Full-state resume: LLM first call receives prior tool result from checkpoint.

        A counter-only resume (iterations = _cp_step, lm_messages untouched) would
        send an empty message list — the sentinel would be absent and this test FAILS.
        Full-state restore (lm_messages = list(_cp_msgs)) passes the sentinel through.
        """
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")
        sentinel = "TOOL_RESULT_SENTINEL_xyz"

        # Simulate crash after step 1 tool call with full conversation state saved.
        store.save_checkpoint(
            "sw:run-ctx",
            {
                CHECKPOINT_KEY_STEP: 1,
                CHECKPOINT_KEY_TOTAL: 4,
                "iterations": 1,
                "tool_calls_count": 1,
                "lm_messages": [
                    {"role": "assistant", "content": "Вызываю dummy"},
                    {"role": "user", "content": f"Результат dummy: {sentinel}"},
                ],
            },
        )

        recording_llm = _RecordingLlm([_final_response("resumed answer")])
        config = _react_config(
            checkpoint_writer=writer, run_id="run-ctx", max_iterations=4
        )
        events = await _run_react_collect(recording_llm, config)

        # Resume status must be emitted (checkpoint was loaded).
        statuses = [
            e.data.get("text", "") if isinstance(e.data, dict) else str(e.data)
            for e in events
            if getattr(e, "type", None) == "status"
        ]
        assert any("resumed" in s for s in statuses), (
            f"Expected 'resumed' status event, got: {statuses}"
        )

        # The LLM's first call must include the prior tool result (lm_messages restored).
        assert recording_llm.received_messages, "LLM was never called"
        first_call_contents = [
            m.get("content", "")
            for m in recording_llm.received_messages[0]
            if isinstance(m, dict)
        ]
        assert any(sentinel in c for c in first_call_contents), (
            f"Expected {sentinel!r} in first LLM call messages — lm_messages not restored. "
            f"Got: {first_call_contents}"
        )


# ---------------------------------------------------------------------------
# OSS-BL-04 — _read_lm_messages element-validation robustness
# ---------------------------------------------------------------------------


class TestReadLmMessagesElementValidation:
    """`_read_lm_messages` must reject lists whose elements are not all dicts.

    Writer-produced checkpoints always store list[dict[str, str]], so the
    normal resume path is unaffected. A third-party CheckpointPort, however,
    could return a list with non-dict elements (e.g. ["foo", 123]); treating
    those as messages would crash downstream in llm_call / the native adapter.
    Fail-safe: a malformed snapshot is treated as "no valid snapshot" (None),
    so the loop starts fresh instead of crashing — consistent with the
    existing absent/empty/non-list -> None behaviour.
    """

    def test_valid_list_of_dicts_returned_unchanged(self) -> None:
        """A non-empty list whose elements are all dicts is returned as-is."""
        snapshot = [{"role": "user", "content": "x"}]
        assert _read_lm_messages({"lm_messages": snapshot}, "lm_messages") is snapshot

    def test_mixed_dict_and_non_dict_elements_returns_none(self) -> None:
        """A list mixing a dict and a non-dict element is rejected (None)."""
        assert (
            _read_lm_messages(
                {"lm_messages": [{"role": "user"}, "not-a-dict"]}, "lm_messages"
            )
            is None
        )

    def test_all_non_dict_elements_returns_none(self) -> None:
        """A list with only non-dict elements is rejected (None)."""
        assert _read_lm_messages({"lm_messages": ["a", "b"]}, "lm_messages") is None

    def test_absent_key_returns_none(self) -> None:
        """An absent key yields None (existing behaviour preserved)."""
        assert _read_lm_messages({}, "lm_messages") is None

    def test_empty_list_returns_none(self) -> None:
        """An empty list yields None (existing behaviour preserved)."""
        assert _read_lm_messages({"lm_messages": []}, "lm_messages") is None

    @pytest.mark.parametrize("bad", ["str", 123])
    def test_non_list_value_returns_none(self, bad: object) -> None:
        """A non-list value yields None (existing behaviour preserved)."""
        assert _read_lm_messages({"lm_messages": bad}, "lm_messages") is None


# ---------------------------------------------------------------------------
# Stage 3 (context-engineering-manus-parity, AGR-004) — tool-schema pinning
# ---------------------------------------------------------------------------


class TestReactToolSchemaSnapshotWiring:
    """Integration-level proof (react_strategy.py, not just the pure module):
    the tool_defs payload sent to the native adapter must stay byte-identical
    across every call of run_react() sharing the same run_id/checkpoint store
    -- exactly like the stable system-prompt prefix from Stage 1/2, extended to
    the tools payload. This is the concrete shape of "two turns of the same
    run": taskloom constructs a FRESH ThinRuntime/run_react() invocation per
    HTTP request, so persistence must flow through the checkpoint substrate,
    not in-process state.
    """

    @pytest.mark.asyncio
    async def test_tools_payload_byte_identical_across_two_calls_of_same_run(
        self,
    ) -> None:
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")
        tool_a = ToolSpec(
            name="alpha",
            description="a",
            parameters={"type": "object", "properties": {}},
        )
        tool_b = ToolSpec(
            name="beta",
            description="b",
            parameters={"type": "object", "properties": {}},
        )
        tool_c_added_later = ToolSpec(
            name="gamma",
            description="c",
            parameters={"type": "object", "properties": {}},
        )

        # --- Turn 1: a tool-call cycle so a checkpoint (incl. schema snapshot) is persisted.
        adapter_1 = _FakeNativeAdapter(
            [
                NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="c1", name="alpha", args={}),)
                ),
                NativeToolCallResult(text="done", tool_calls=()),
            ]
        )
        llm_1 = _SequencedLlm(['{"answer": "ok"}'])
        config_1 = _native_config(checkpoint_writer=writer, run_id="run-schema-1")
        await _run_react_native_collect(
            llm_1, adapter_1, config_1, tools=[tool_b, tool_a]
        )

        assert adapter_1.received_tools, "adapter_1 was never called"
        turn_1_payload = adapter_1.received_tools[0]
        assert [t["name"] for t in turn_1_payload] == ["alpha", "beta"]

        # --- Turn 2: a SEPARATE run_react() call (fresh adapter/ThinRuntime, same
        # run_id/store), simulating a later HTTP request against the same run.
        # A "later turn discovered a new tool" (gamma) must NOT change the payload.
        adapter_2 = _FakeNativeAdapter(
            [NativeToolCallResult(text="done2", tool_calls=())]
        )
        llm_2 = _SequencedLlm(['{"answer": "ok2"}'])
        config_2 = _native_config(checkpoint_writer=writer, run_id="run-schema-1")
        await _run_react_native_collect(
            llm_2, adapter_2, config_2, tools=[tool_c_added_later, tool_a, tool_b]
        )

        assert adapter_2.received_tools, "adapter_2 was never called"
        turn_2_payload = adapter_2.received_tools[0]

        assert turn_2_payload == turn_1_payload, (
            "Tool-call schema payload must be byte-identical across turns of the "
            f"same run (AGR-004). Turn 1: {turn_1_payload!r}, turn 2: {turn_2_payload!r}"
        )
        assert "gamma" not in [t["name"] for t in turn_2_payload], (
            "A tool discovered on a later turn must not leak into the pinned schema"
        )

    @pytest.mark.asyncio
    async def test_pinning_holds_even_when_first_turn_makes_no_tool_call(
        self,
    ) -> None:
        """Fix-cycle 1 (M-1, codex round 1): the FIRST turn of a run may finish
        with NO tool call at all (immediate final answer) -- the pinned schema
        must still be persisted (not only inside after_tool_call()), so a
        SECOND call of the same run_id sees the SAME pinned tool set even
        though the live registry handed it a different/larger list."""
        store = _make_store()
        writer = _make_writer(store, namespace="sw:")
        tool_a = ToolSpec(
            name="alpha",
            description="a",
            parameters={"type": "object", "properties": {}},
        )
        tool_b = ToolSpec(
            name="beta",
            description="b",
            parameters={"type": "object", "properties": {}},
        )

        # --- Turn 1: NO tool call at all -- immediate final answer.
        adapter_1 = _FakeNativeAdapter(
            [NativeToolCallResult(text="done", tool_calls=())]
        )
        llm_1 = _SequencedLlm(['{"answer": "ok"}'])
        config_1 = _native_config(checkpoint_writer=writer, run_id="run-schema-notool")
        await _run_react_native_collect(llm_1, adapter_1, config_1, tools=[tool_a])

        assert adapter_1.received_tools, "adapter_1 was never called"
        turn_1_payload = adapter_1.received_tools[0]
        assert [t["name"] for t in turn_1_payload] == ["alpha"]

        # --- Turn 2: a SEPARATE run_react() call, same run_id, but the live
        # registry now hands it a DIFFERENT (larger) tool list -- the pin from
        # turn 1 (which never wrote a checkpoint via after_tool_call, since no
        # tool call happened) must still hold.
        adapter_2 = _FakeNativeAdapter(
            [NativeToolCallResult(text="done2", tool_calls=())]
        )
        llm_2 = _SequencedLlm(['{"answer": "ok2"}'])
        config_2 = _native_config(checkpoint_writer=writer, run_id="run-schema-notool")
        await _run_react_native_collect(
            llm_2, adapter_2, config_2, tools=[tool_b, tool_a]
        )

        assert adapter_2.received_tools, "adapter_2 was never called"
        turn_2_payload = adapter_2.received_tools[0]
        assert turn_2_payload == turn_1_payload, (
            "Pinning must hold even when the first turn made no tool call at all. "
            f"Turn 1: {turn_1_payload!r}, turn 2: {turn_2_payload!r}"
        )
        assert "beta" not in [t["name"] for t in turn_2_payload], (
            "A tool absent from turn 1's pinned snapshot must never leak in later, "
            "even when turn 1 itself never triggered a tool-call checkpoint write"
        )
