"""Tests for kernel-wiring spec, Task 1 — follow-up requeue at natural end of ReAct loop.

TDD Red phase: tests before implementation.
Covers Requirement 1 (REQ-001..004, REQ-013/014) and Scenario 1 of
``.memory-bank/specs/kernel-wiring/requirements.md``:

``RuntimeConfig.get_followup_messages`` is declared but has no functional
call site (I-008). This suite proves the new ``maybe_followup_requeue``
helper (``mid_run_hooks.py``) wired into BOTH natural-end seams of
``run_react`` (text-ReAct final envelope + native tool-calling loop with no
further tool calls):

- continues the loop for exactly one extra turn when the hook returns a
  non-empty message list, then finalizes once it returns empty (REQ-001);
- never runs away — bounded by the existing ``iterations < max_iterations``
  budget, no fresh counter (REQ-002);
- is a true no-op (no ``KernelContext`` snapshot built) when
  ``get_followup_messages`` is unset — byte-identical default (REQ-003);
- behaves identically on the text-ReAct seam and the native tool-calling
  seam (REQ-004), INCLUDING the streaming text-ReAct sub-path (GPT-5.5
  review MAJOR — a streaming turn used to surface the requeued turn's
  answer via ``assistant_delta`` before the follow-up decision was made,
  because ``stream_llm_call``'s ``FinalMessageDeltaExtractor`` streamed
  ``final_message`` content out during the LLM call itself, well before
  ``maybe_followup_requeue`` ever ran).

Shared fakes/helpers live in ``_followup_fakes.py`` (extracted for the
400-line file-size cap — ``_graph_streaming_fakes.py``/``_fake_redis.py``
convention).
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent

from ._followup_fakes import (
    TOOL,
    FinishNoToolsNativeAdapter,
    SequentialStreamingLLM,
    collect,
    noop_tool,
    unreachable_llm,
)

# ---------------------------------------------------------------------------
# REQ-001 / Scenario 1: requeue continues the loop, then finalizes once
# ---------------------------------------------------------------------------


class TestFollowupRequeueContinuesLoop:
    @pytest.mark.asyncio
    async def test_followup_requeue_continues_loop_within_max_iterations(
        self,
    ) -> None:
        # Arrange: the model finalizes on every turn; the follow-up hook
        # returns ONE message the first time it is asked, empty thereafter.
        call_count = 0
        seen_messages: list[list[dict[str, Any]]] = []

        async def llm_call(messages: list, system_prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            seen_messages.append([dict(m) for m in messages])
            return json.dumps({"type": "final", "final_message": f"done-{call_count}"})

        followup_calls = 0

        def _get_followup(ctx: Any) -> list[Message]:
            nonlocal followup_calls
            followup_calls += 1
            if followup_calls == 1:
                return [Message(role="user", content="FOLLOWUP_MARKER")]
            return []

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            get_followup_messages=_get_followup,
        )
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": noop_tool}, config=config
        )

        # Act
        events = await collect(runtime)

        # Assert: exactly one extra model turn happened (natural end -> requeue
        # -> second natural end -> finalize), and finalize fired exactly once.
        assert call_count == 2, f"expected exactly 2 model turns, got {call_count}"
        assert followup_calls == 2
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert not any(e.is_error for e in events)
        # The follow-up message must have reached the model on the extra turn.
        assert "FOLLOWUP_MARKER" not in json.dumps(seen_messages[0])
        assert "FOLLOWUP_MARKER" in json.dumps(seen_messages[1])


# ---------------------------------------------------------------------------
# REQ-002: bounded by the existing iteration budget — no infinite loop
# ---------------------------------------------------------------------------


class TestFollowupRequeueTermination:
    @pytest.mark.asyncio
    async def test_followup_requeue_terminates_on_max_iterations(self) -> None:
        # Arrange: the follow-up hook ALWAYS returns a message — without the
        # existing iteration budget this would loop forever.
        call_count = 0

        async def llm_call(messages: list, system_prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({"type": "final", "final_message": "done"})

        def _always_followup(ctx: Any) -> list[Message]:
            return [Message(role="user", content="AGAIN")]

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=3,
            max_tool_calls=10,
            get_followup_messages=_always_followup,
        )
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": noop_tool}, config=config
        )

        # Act
        events = await collect(runtime)

        # Assert: the run terminates (produces a terminal event; no hang) and
        # never exceeds the configured iteration budget.
        assert events, "must yield a terminal event, not hang forever"
        assert call_count <= 3, (
            f"model turns ({call_count}) must be bounded by max_iterations=3"
        )
        terminal = events[-1]
        assert terminal.type in ("error", "final"), (
            f"expected a terminal event, got {terminal.type}"
        )


# ---------------------------------------------------------------------------
# REQ-003: None default is byte-identical — no snapshot built
# ---------------------------------------------------------------------------


class TestFollowupNoneDefault:
    @pytest.mark.asyncio
    async def test_followup_none_finalizes_byte_identical_no_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.runtime.thin import mid_run_hooks

        snapshot_calls = 0
        original_build_turn_snapshot = mid_run_hooks.build_turn_snapshot

        def _spy_build_turn_snapshot(*args: Any, **kwargs: Any) -> Any:
            nonlocal snapshot_calls
            snapshot_calls += 1
            return original_build_turn_snapshot(*args, **kwargs)

        monkeypatch.setattr(
            mid_run_hooks, "build_turn_snapshot", _spy_build_turn_snapshot
        )

        async def llm_call(messages: list, system_prompt: str) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        # get_followup_messages defaults to None — not set here.
        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": noop_tool}, config=config
        )

        # Act
        events = await collect(runtime)

        # Assert: unchanged finalize path, and no KernelContext snapshot built.
        assert any(e.is_final for e in events)
        assert not any(e.is_error for e in events)
        assert snapshot_calls == 0, (
            "get_followup_messages=None must not build a KernelContext snapshot"
        )


# ---------------------------------------------------------------------------
# REQ-004: parity between the text-ReAct seam and the native tool-calling seam
# ---------------------------------------------------------------------------


class TestFollowupRequeueParity:
    @pytest.mark.asyncio
    async def test_followup_requeue_parity_text_and_native_seams(self) -> None:
        # --- text-ReAct seam ---
        text_call_count = 0
        text_seen_messages: list[list[dict[str, Any]]] = []

        async def text_llm_call(messages: list, system_prompt: str) -> str:
            nonlocal text_call_count
            text_call_count += 1
            text_seen_messages.append([dict(m) for m in messages])
            return json.dumps({"type": "final", "final_message": "done"})

        text_followup_calls = 0

        def _text_followup(ctx: Any) -> list[Message]:
            nonlocal text_followup_calls
            text_followup_calls += 1
            if text_followup_calls == 1:
                return [Message(role="user", content="FOLLOWUP_MARKER")]
            return []

        text_config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            get_followup_messages=_text_followup,
        )
        text_events: list[RuntimeEvent] = []
        async for ev in run_react(
            text_llm_call,
            ToolExecutor(local_tools={"noop": noop_tool}),
            [Message(role="user", content="go")],
            "system",
            [TOOL],
            text_config,
            time.monotonic(),
        ):
            text_events.append(ev)

        assert text_call_count == 2
        assert "FOLLOWUP_MARKER" in json.dumps(text_seen_messages[1])
        assert len([e for e in text_events if e.is_final]) == 1

        # --- native tool-calling seam ---
        native_followup_calls = 0

        def _native_followup(ctx: Any) -> list[Message]:
            nonlocal native_followup_calls
            native_followup_calls += 1
            if native_followup_calls == 1:
                return [Message(role="user", content="FOLLOWUP_MARKER")]
            return []

        adapter = FinishNoToolsNativeAdapter(["native-done-1", "native-done-2"])
        native_config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=True,
            max_iterations=10,
            max_tool_calls=10,
            get_followup_messages=_native_followup,
        )
        native_events: list[RuntimeEvent] = []
        async for ev in run_react(
            unreachable_llm,
            ToolExecutor(local_tools={"noop": noop_tool}),
            [Message(role="user", content="go")],
            "system",
            [TOOL],
            native_config,
            time.monotonic(),
            native_adapter=adapter,
        ):
            native_events.append(ev)

        # Assert: identical shape of behavior — one requeued turn, one finalize.
        assert adapter.call_count == 2
        assert native_followup_calls == 2
        assert "FOLLOWUP_MARKER" in json.dumps(adapter.seen_messages[1])
        assert len([e for e in native_events if e.is_final]) == 1
        assert not any(e.is_error for e in native_events)


# ---------------------------------------------------------------------------
# REQ-004 (streaming sub-path): a requeued turn must never surface its answer
# via assistant_delta before the follow-up decision is made
# ---------------------------------------------------------------------------


class TestFollowupRequeueStreamingParity:
    @pytest.mark.asyncio
    async def test_followup_requeue_streaming_suppresses_premature_final(
        self,
    ) -> None:
        # Arrange: turn 1 streams "FIRST_ANSWER" (a requeue is coming right
        # after it — must NOT be surfaced); turn 2 streams "SECOND_ANSWER"
        # (the true natural end).
        llm = SequentialStreamingLLM(["FIRST_ANSWER", "SECOND_ANSWER"])

        followup_calls = 0

        def _get_followup(ctx: Any) -> list[Message]:
            nonlocal followup_calls
            followup_calls += 1
            if followup_calls == 1:
                return [Message(role="user", content="FOLLOWUP_MARKER")]
            return []

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            get_followup_messages=_get_followup,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": noop_tool}, config=config
        )

        # Act
        events = await collect(runtime)

        # Assert: the FIRST (requeued) answer must never reach the consumer —
        # neither as a streamed delta nor as a final — only the SECOND (true
        # end) answer surfaces, exactly once.
        deltas = [e for e in events if e.type == "assistant_delta"]
        delta_text = "".join(d.text for d in deltas)
        assert "FIRST_ANSWER" not in delta_text, (
            "the requeued turn's answer leaked via assistant_delta before "
            "the follow-up decision — REQ-004 streaming parity violated"
        )
        assert "SECOND_ANSWER" in delta_text

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert finals[0].text == "SECOND_ANSWER"
        assert "FIRST_ANSWER" not in finals[0].text
        assert llm.call_count == 2
        assert followup_calls == 2
