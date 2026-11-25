"""Tests for kernel-patterns spec, Task 1 — generic mid-run control hooks.

TDD Red phase: tests before implementation.
Covers REQ-010: ``should_stop_after_turn`` / ``get_steering_messages`` /
``transform_context`` on ``RuntimeConfig``, wired into the react turn-based
loop and reachable by the kernel via ``ctx.config.<hook>``.

Default (all hooks None) must remain byte-identical to pre-H4 behaviour —
covered by the full existing suite; this file exercises the opt-in paths.

GPT-5.5 review findings (post-Task-1, both MAJOR):
- FINDING 1: native tool-call turns bypassed post-turn hooks entirely
  (``should_stop_after_turn`` / ``get_steering_messages`` only ran on the
  text-ReAct branch).
- FINDING 2: a graceful stop emitted only a ``status`` event, never a
  terminal ``RuntimeEvent.final`` — losing accumulated messages/metrics.

conformance-audit Basket 1 item 6 (plan stage 30): ``transform_context`` was
an open seam — a raw ``Callable[[list], list]`` with no contract stopping a
future implementation from mutating/reordering/dropping the stable prefix of
``lm_messages``, which would silently break build-once / KV-cache prompt
stability. 0 real consumers exist today (grep-verified); closed with a
prefix-immutable, tail-append-only contract enforced in
``apply_transform_context`` itself (``TestTransformContextPrefixContract``).
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.mid_run_hooks import (
    TransformContextContractError,
    apply_transform_context,
)
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOL = ToolSpec(name="noop", description="do nothing", parameters={})


def _noop_tool(**kwargs: object) -> str:
    return json.dumps({"result": "ok"})


async def _collect(runtime: ThinRuntime) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="go")],
        system_prompt="You are a helper.",
        active_tools=[_TOOL],
        mode_hint="react",
    ):
        events.append(ev)
    return events


class _InfiniteToolCallLLM:
    """Always returns a tool_call — without a stop hook the loop keeps going."""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        return json.dumps({"type": "tool_call", "tool": {"name": "noop", "args": {}}})


# ---------------------------------------------------------------------------
# should_stop_after_turn
# ---------------------------------------------------------------------------


class TestStopAfterTurnHook:
    """should_stop_after_turn: True after a turn ends the loop gracefully."""

    @pytest.mark.asyncio
    async def test_stop_after_turn_hook_ends_loop(self) -> None:
        # Arrange: LLM would loop forever (always tool_call); hook stops after turn 1.
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: True,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )

        # Act
        events = await _collect(runtime)

        # Assert: exactly one turn executed, no error, loop ended gracefully.
        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(finished) == 1
        assert llm.call_count == 1
        assert not any(e.is_error for e in events), (
            f"Expected graceful stop, no error events; got: "
            f"{[e.data for e in events if e.is_error]}"
        )
        status_texts = [e.text for e in events if e.type == "status"]
        assert any("stopped_after_turn" in t for t in status_texts)

    @pytest.mark.asyncio
    async def test_stop_after_turn_hook_false_keeps_looping(self) -> None:
        # Arrange: hook always returns False — behaves like default (unset).
        responses_used: list[str] = []

        async def llm_call(messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
            if len(responses_used) < 2:
                responses_used.append("tool_call")
                return json.dumps(
                    {"type": "tool_call", "tool": {"name": "noop", "args": {}}}
                )
            return json.dumps({"type": "final", "final_message": "done"})

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: False,
        )
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": _noop_tool}, config=config
        )

        # Act
        events = await _collect(runtime)

        # Assert: loop continued to natural completion (2 tool calls + final).
        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(finished) == 2
        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_stop_after_turn_emits_terminal_final_event(self) -> None:
        """FINDING 2 (GPT-5.5 review, text-ReAct branch): graceful stop must
        yield a terminal ``final`` RuntimeEvent — not just a status — that
        preserves the tool-call + tool-result messages accumulated so far.
        """
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: True,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )

        events = await _collect(runtime)

        finals = [e for e in events if e.is_final]
        assert finals, "graceful stop must emit a terminal final event, not just status"
        new_msgs = finals[-1].data["new_messages"]
        assert any(m.get("role") == "tool" for m in new_msgs), (
            "final event must preserve the accumulated tool-call/tool-result messages"
        )
        assert "metrics" in finals[-1].data


# ---------------------------------------------------------------------------
# get_steering_messages
# ---------------------------------------------------------------------------


class TestSteeringMessagesHook:
    """get_steering_messages: injected between turns, visible on the NEXT call."""

    @pytest.mark.asyncio
    async def test_steering_messages_injected_between_turns(self) -> None:
        # Arrange: capture the messages the model sees on every call.
        seen_messages: list[list[dict[str, Any]]] = []
        call_count = 0

        async def llm_call(messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
            nonlocal call_count
            seen_messages.append([dict(m) for m in messages])
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {"type": "tool_call", "tool": {"name": "noop", "args": {}}}
                )
            return json.dumps({"type": "final", "final_message": "done"})

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=5,
            max_tool_calls=5,
            get_steering_messages=lambda ctx: [
                Message(role="user", content="STEERING_MARKER")
            ],
        )
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": _noop_tool}, config=config
        )

        # Act
        await _collect(runtime)

        # Assert: marker absent on turn 1's input, present on turn 2's input.
        assert len(seen_messages) == 2
        turn_1_texts = json.dumps(seen_messages[0])
        turn_2_texts = json.dumps(seen_messages[1])
        assert "STEERING_MARKER" not in turn_1_texts
        assert "STEERING_MARKER" in turn_2_texts


# ---------------------------------------------------------------------------
# transform_context
# ---------------------------------------------------------------------------


class TestTransformContextHook:
    """transform_context: applied to the LM-facing messages before the model call."""

    @pytest.mark.asyncio
    async def test_transform_context_applied_before_model(self) -> None:
        # Arrange: capture the exact message list handed to the model.
        seen_messages: list[list[dict[str, Any]]] = []

        async def llm_call(messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
            seen_messages.append([dict(m) for m in messages])
            return json.dumps({"type": "final", "final_message": "done"})

        def _transform(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [*msgs, {"role": "user", "content": "TRANSFORMED_MARKER"}]

        config = RuntimeConfig(runtime_name="thin", transform_context=_transform)
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": _noop_tool}, config=config
        )

        # Act
        await _collect(runtime)

        # Assert: the FIRST (only) call already carries the transformed marker.
        assert len(seen_messages) == 1
        assert "TRANSFORMED_MARKER" in json.dumps(seen_messages[0])


# ---------------------------------------------------------------------------
# transform_context contract: prefix-immutable, tail-append-only
# (conformance-audit Basket 1 item 6 / plan stage 30)
# ---------------------------------------------------------------------------


class TestTransformContextPrefixContract:
    """``transform_context`` may only APPEND to the tail of ``lm_messages``.

    Contract: every entry present before the call must survive, byte-for-byte
    identical and in the same order, at the head of the returned list. This
    protects build-once / KV-cache prompt-prefix stability from a future
    ``transform_context`` implementation that reorders, rewrites, or drops
    earlier entries. 0 real consumers exist today — enforced now, before the
    seam has any caller to break compatibility with.
    """

    def test_transform_context_appends_only_to_tail(self) -> None:
        # Arrange
        original = [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "turn 1"},
        ]

        def _append_only(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [*msgs, {"role": "user", "content": "TAIL_MARKER"}]

        config = RuntimeConfig(runtime_name="thin", transform_context=_append_only)

        # Act
        result = apply_transform_context(config, original)

        # Assert: prefix byte-identical, only a tail entry was added.
        assert result[: len(original)] == original
        assert result[len(original) :] == [{"role": "user", "content": "TAIL_MARKER"}]

    def test_transform_context_mutating_prefix_entry_is_rejected(self) -> None:
        # Arrange
        original = [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "turn 1"},
        ]

        def _mutate_prefix(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            mutated = [dict(m) for m in msgs]
            mutated[0]["content"] = "TAMPERED"
            return mutated

        config = RuntimeConfig(runtime_name="thin", transform_context=_mutate_prefix)

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, original)

    def test_transform_context_reordering_prefix_is_rejected(self) -> None:
        # Arrange
        original = [
            {"role": "system", "content": "a"},
            {"role": "user", "content": "b"},
        ]

        def _reorder(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return list(reversed(msgs))

        config = RuntimeConfig(runtime_name="thin", transform_context=_reorder)

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, original)

    def test_transform_context_dropping_prefix_entry_is_rejected(self) -> None:
        # Arrange
        original = [
            {"role": "system", "content": "a"},
            {"role": "user", "content": "b"},
        ]

        def _drop(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return msgs[1:]

        config = RuntimeConfig(runtime_name="thin", transform_context=_drop)

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, original)

    def test_transform_context_in_place_prefix_mutation_is_rejected(self) -> None:
        """verify-cycle finding: comparing the live object against itself
        AFTER the hook ran let an in-place mutation that returns the SAME
        list object bypass the check (a list always equals itself). The
        contract must compare against a baseline snapshot taken BEFORE the
        hook runs.
        """
        # Arrange
        original = [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "turn 1"},
        ]

        def _mutate_in_place_same_object(
            msgs: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            msgs[0]["content"] = "TAMPERED_IN_PLACE"
            return msgs

        config = RuntimeConfig(
            runtime_name="thin", transform_context=_mutate_in_place_same_object
        )

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, original)

    def test_transform_context_nested_prefix_mutation_is_rejected(self) -> None:
        """Top-level list identity/order can stay untouched while a NESTED
        dict inside a prefix entry is mutated in place — must be rejected too
        (a shallow prefix-equality/identity check would miss this).
        """
        # Arrange
        original = [
            {"role": "system", "content": "stable prefix", "meta": {"turn": 0}},
            {"role": "user", "content": "turn 1"},
        ]

        def _mutate_nested(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            msgs[0]["meta"]["turn"] = 999
            return msgs

        config = RuntimeConfig(runtime_name="thin", transform_context=_mutate_nested)

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, original)

    def test_transform_context_lying_slice_container_is_rejected(self) -> None:
        """GPT-5.5 review finding: validating ``transformed[:prefix_len]``
        trusts the slice/equality behaviour of the OBJECT the hook returned,
        then hands that SAME object downstream. A container whose slice
        access reports an honest (baseline-matching) prefix while iteration
        — what ``list(...)``/downstream consumers actually materialize —
        exposes tampered content could smuggle a poisoned prefix past a
        slice-only check. The contract must validate (and return) the SAME
        materialized data downstream code will actually see.
        """
        # Arrange
        honest_prefix = [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "turn 1"},
        ]
        tampered_prefix = [
            {"role": "system", "content": "TAMPERED"},
            {"role": "user", "content": "turn 1"},
        ]
        tail = [{"role": "user", "content": "TAIL_MARKER"}]

        class _LyingSliceContainer:
            """Slice access lies (returns the honest prefix); iteration —
            what ``list()``/a ``for`` loop actually consumes — exposes the
            real, tampered content instead."""

            def __init__(self) -> None:
                self._real = [*tampered_prefix, *tail]

            def __getitem__(self, key: object) -> object:
                if isinstance(key, slice):
                    return list(honest_prefix)
                return self._real[key]  # type: ignore[index]

            def __iter__(self) -> Any:
                return iter(self._real)

            def __len__(self) -> int:
                return len(self._real)

        def _lying_transform(
            msgs: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            return _LyingSliceContainer()  # type: ignore[return-value]

        config = RuntimeConfig(runtime_name="thin", transform_context=_lying_transform)

        # Act / Assert
        with pytest.raises(TransformContextContractError):
            apply_transform_context(config, honest_prefix)

    def test_transform_context_none_hook_stays_noop_passthrough(self) -> None:
        # Arrange: default (unset) hook — byte-identical passthrough, no contract check needed.
        original = [{"role": "user", "content": "hello"}]
        config = RuntimeConfig(runtime_name="thin")

        # Act
        result = apply_transform_context(config, original)

        # Assert
        assert result is original


# ---------------------------------------------------------------------------
# GPT-5.5 review FINDING 1 + 2 — native tool-calling branch parity
# ---------------------------------------------------------------------------


class _StopAfterOneNativeAdapter:
    """Native adapter returning ONE tool-call turn; asserts it is never re-called.

    Used to prove ``should_stop_after_turn`` actually halts the loop on the
    native tool-calling path (pre-fix: the native branch ``continue``d
    immediately after a tool-call turn, so the hook never even ran and the
    adapter would have been called again).
    """

    def __init__(self) -> None:
        self.call_count = 0

    async def call_with_tools(
        self, messages: Any, system_prompt: str, tools: Any, **kwargs: Any
    ) -> NativeToolCallResult:
        self.call_count += 1
        assert self.call_count == 1, (
            "should_stop_after_turn=True must stop the loop after the first "
            "native tool-call turn; the native adapter must not be re-invoked"
        )
        return NativeToolCallResult(
            tool_calls=(NativeToolCall(id="n1", name="noop", args={}),)
        )


async def _unreachable_text_llm(messages: Any, prompt: Any, **kwargs: Any) -> str:
    raise AssertionError(
        "text-ReAct llm_call must not be reached — native adapter handles the turn"
    )


class TestNativeToolCallingPostTurnHooks:
    """Post-turn hooks (should_stop_after_turn / get_steering_messages) must
    fire identically for native tool-calling agents (use_native_tools=True),
    not only the text-ReAct branch (GPT-5.5 review FINDING 1)."""

    @pytest.mark.asyncio
    async def test_stop_after_turn_fires_for_native_tool_agent(self) -> None:
        adapter = _StopAfterOneNativeAdapter()
        config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=True,
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: True,
        )

        events: list[RuntimeEvent] = []
        async for ev in run_react(
            _unreachable_text_llm,
            ToolExecutor(local_tools={"noop": _noop_tool}),
            [Message(role="user", content="go")],
            "system",
            [_TOOL],
            config,
            time.monotonic(),
            native_adapter=adapter,
        ):
            events.append(ev)

        # The stop hook must have fired after turn 1 — the adapter's own
        # assertion (call_count == 1) already enforces "no second turn"; here
        # we additionally require a graceful, non-error stop with a terminal
        # final event that preserves the accumulated native tool messages
        # (FINDING 2, verified on the native path too).
        assert adapter.call_count == 1
        assert not any(e.is_error for e in events), (
            f"expected graceful stop, no errors; got: "
            f"{[e.data for e in events if e.is_error]}"
        )
        status_texts = [e.text for e in events if e.type == "status"]
        assert any("stopped_after_turn" in t for t in status_texts)
        finals = [e for e in events if e.is_final]
        assert finals, (
            "graceful stop on the native tool-calling path must emit a "
            "terminal final event (FINDING 2)"
        )
        new_msgs = finals[-1].data["new_messages"]
        assert any(m.get("role") == "tool" for m in new_msgs), (
            "final event must preserve the accumulated native tool-call messages"
        )

    @pytest.mark.asyncio
    async def test_steering_messages_injected_for_native_tool_agent(self) -> None:
        # Arrange: two native turns — first executes a tool call, second (after
        # steering was injected) returns no further tool calls (loop finishes).
        responses = [
            NativeToolCallResult(
                tool_calls=(NativeToolCall(id="n1", name="noop", args={}),)
            ),
            NativeToolCallResult(text="done", tool_calls=()),
        ]
        seen_messages: list[list[dict[str, Any]]] = []

        class _RecordingNativeAdapter:
            async def call_with_tools(
                self, messages: Any, system_prompt: str, tools: Any, **kwargs: Any
            ) -> NativeToolCallResult:
                seen_messages.append([dict(m) for m in messages])
                return responses.pop(0)

        config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=True,
            max_iterations=10,
            max_tool_calls=10,
            get_steering_messages=lambda ctx: [
                Message(role="user", content="STEERING_MARKER")
            ],
        )

        async def _finalize_llm(messages: Any, prompt: Any, **kwargs: Any) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        events: list[RuntimeEvent] = []
        async for ev in run_react(
            _finalize_llm,
            ToolExecutor(local_tools={"noop": _noop_tool}),
            [Message(role="user", content="go")],
            "system",
            [_TOOL],
            config,
            time.monotonic(),
            native_adapter=_RecordingNativeAdapter(),
        ):
            events.append(ev)

        # Assert: marker absent on the FIRST native call, present on the SECOND
        # — proving get_steering_messages fires between native turns too.
        assert len(seen_messages) == 2
        turn_1_texts = json.dumps(seen_messages[0])
        turn_2_texts = json.dumps(seen_messages[1])
        assert "STEERING_MARKER" not in turn_1_texts
        assert "STEERING_MARKER" in turn_2_texts
        assert not any(e.is_error for e in events)


# ---------------------------------------------------------------------------
# GPT-5.5 review round 2 (MAJOR) — graceful-stop final must NOT zero usage
# ---------------------------------------------------------------------------


class TestStopAfterTurnUsageParity:
    """A graceful stop must build its terminal ``final`` via the SAME
    usage/metrics computation path (``_build_usage`` + ``_build_metrics``)
    that ``finalization._make_final_event`` uses on a normal loop exit —
    not a hand-rolled zeroed final. Otherwise ThinRuntime's cost tracker
    (which reads the final event's ``usage``/``metrics``) records 0 tokens /
    0 cost for a graceful stop and can miss a budget signal.
    """

    @pytest.mark.asyncio
    async def test_stop_after_turn_final_reports_accumulated_usage(self) -> None:
        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: True,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )

        events = await _collect(runtime)

        finals = [e for e in events if e.is_final]
        assert finals, "graceful stop must emit a terminal final event"
        metrics = finals[-1].data["metrics"]
        usage = finals[-1].data.get("usage", {})
        assert metrics["tokens_in"] > 0, (
            f"stop-final must NOT zero usage/metrics; got metrics={metrics}"
        )
        assert usage.get("input_tokens", 0) > 0
        # usage and metrics must agree (same _build_usage output threaded through
        # _build_metrics) — not two independently-computed numbers.
        assert usage.get("input_tokens") == metrics["tokens_in"]
        assert usage.get("output_tokens") == metrics["tokens_out"]

    @pytest.mark.asyncio
    async def test_stop_after_turn_triggers_budget_on_stop_path(self) -> None:
        """With a near-zero token budget, the stop path must surface the same
        ``budget_exceeded`` signal the normal-exit path would. This proves the
        stop-final's usage actually reaches ThinRuntime's CostTracker (reachable
        on the stop path), not merely cosmetically non-zero.
        """
        from swarmline.runtime.cost import CostBudget

        llm = _InfiniteToolCallLLM()
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_tool_calls=10,
            should_stop_after_turn=lambda ctx: True,
            cost_budget=CostBudget(max_total_tokens=1, action_on_exceed="error"),
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"noop": _noop_tool}, config=config
        )

        events = await _collect(runtime)

        assert any(
            e.type == "error" and e.data.get("kind") == "budget_exceeded"
            for e in events
        ), f"expected budget_exceeded on the stop path; got: {[e.data for e in events]}"

    @pytest.mark.asyncio
    async def test_stop_final_usage_matches_normal_final_computation(self) -> None:
        """Direct parity check against ``finalization``'s own building blocks:
        ``run_post_turn_hooks``' stop-final usage/metrics must equal exactly
        what ``_build_usage``/``_build_metrics`` compute for the SAME
        (lm_messages, prompt, text) inputs — proving the stop path reuses the
        normal-exit computation rather than hand-rolling a zeroed final.
        """
        from swarmline.runtime.thin.finalization import _build_usage
        from swarmline.runtime.thin.helpers import _build_metrics
        from swarmline.runtime.thin.mid_run_hooks import run_post_turn_hooks

        config = RuntimeConfig(
            runtime_name="thin",
            should_stop_after_turn=lambda ctx: True,
        )
        lm_messages: list[dict[str, Any]] = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "Вызываю noop"},
            {"role": "user", "content": 'Результат noop: {"result": "ok"}'},
        ]
        prompt = "You are a helper. <tools>noop</tools>"
        turn_text = json.dumps(
            {"type": "tool_call", "tool": {"name": "noop", "args": {}}}
        )
        start_time = time.monotonic()

        async def _unreachable_llm(*args: Any, **kwargs: Any) -> str:
            raise AssertionError(
                "should_stop_after_turn must not trigger an extra model call"
            )

        outcome = run_post_turn_hooks(
            config=config,
            llm_call=_unreachable_llm,
            messages=[Message(role="user", content="go")],
            new_messages=[
                Message(role="assistant", content="", metadata={"tool_call": "noop"}),
                Message(role="tool", content=json.dumps({"result": "ok"}), name="noop"),
            ],
            system_prompt="You are a helper.",
            start_time=start_time,
            checkpoint=None,
            iterations=1,
            tool_calls_count=1,
            lm_messages=lm_messages,
            prompt=prompt,
            turn_text=turn_text,
        )

        assert outcome.should_stop
        assert outcome.stop_final_event is not None

        expected_usage = _build_usage(lm_messages, prompt, turn_text)
        expected_metrics = _build_metrics(
            start_time,
            config,
            iterations=1,
            tool_calls=1,
            tokens_in=expected_usage["input_tokens"],
            tokens_out=expected_usage["output_tokens"],
        )

        stop_data = outcome.stop_final_event.data
        assert stop_data["usage"] == expected_usage
        assert stop_data["metrics"]["tokens_in"] == expected_metrics.tokens_in
        assert stop_data["metrics"]["tokens_out"] == expected_metrics.tokens_out


# ---------------------------------------------------------------------------
# Backward compatibility: all hooks default None
# ---------------------------------------------------------------------------


class TestMidRunHooksDefaultNone:
    """Default (unset) hooks: config carries None, no behaviour change."""

    def test_hooks_default_to_none(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        assert config.should_stop_after_turn is None
        assert config.get_steering_messages is None
        assert config.get_followup_messages is None
        assert config.transform_context is None

    @pytest.mark.asyncio
    async def test_default_config_react_loop_unaffected(self) -> None:
        # A plain react loop with all hooks unset behaves exactly as before.
        async def llm_call(messages: list, system_prompt: str) -> str:  # type: ignore[type-arg]
            return json.dumps({"type": "final", "final_message": "done"})

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(
            llm_call=llm_call, local_tools={"noop": _noop_tool}, config=config
        )

        events = await _collect(runtime)
        assert any(e.is_final for e in events)
        assert not any(e.is_error for e in events)
