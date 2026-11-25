"""Tests for swarmline.context.recitation_input_filter -- Stage 5
(context-engineering-manus-parity): plan/todo recitation by cadence of
MEANINGFUL (human) turns.

TDD file: written BEFORE the implementation. Covers count_human_turns(),
should_recite(), and RecitationInputFilter in isolation, plus a joint
byte-stability test with Stage 1's build_stable_prefix().

Hardening (pre-judge, per team-lead + codex round 1): an end-to-end test
proving the self-poisoning/cadence-drift concern is structurally impossible
-- recitation text injected into `messages`/`lm_messages` for THIS call must
NEVER surface in `new_messages`/`RuntimeEvent.final`, the only channel a
caller uses to persist history for a FUTURE call.
"""

from __future__ import annotations

import json
import time

import pytest

from swarmline.context.recitation_input_filter import (
    RECITATION_CADENCE,
    RecitationInputFilter,
    count_human_turns,
    should_recite,
)
from swarmline.context.stable_prefix import build_stable_prefix
from swarmline.domain_types import Message
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig


def _user(content: str = "hi") -> Message:
    return Message(role="user", content=content)


def _assistant(content: str = "ok") -> Message:
    return Message(role="assistant", content=content)


def _tool(content: str = "result", name: str = "some_tool") -> Message:
    return Message(role="tool", content=content, name=name)


class TestCountHumanTurns:
    def test_counts_only_user_role_messages(self) -> None:
        messages = [_user(), _assistant(), _tool(), _user(), _tool()]
        assert count_human_turns(messages) == 2

    def test_empty_history_is_zero(self) -> None:
        assert count_human_turns([]) == 0

    def test_tool_and_assistant_only_is_zero(self) -> None:
        """Tool-round bookkeeping (assistant + tool messages) alone never
        counts as a human turn, no matter how many accumulate."""
        messages = [_assistant(), _tool(), _assistant(), _tool(), _assistant()]
        assert count_human_turns(messages) == 0


class TestShouldRecite:
    def test_first_human_turn_recites(self) -> None:
        assert should_recite(1) is True

    def test_zero_turns_never_recites(self) -> None:
        assert should_recite(0) is False

    def test_negative_turns_never_recites(self) -> None:
        assert should_recite(-1) is False

    @pytest.mark.parametrize("count", [2, 3, 4, 6, 7, 8, 9])
    def test_non_cadence_turns_do_not_recite(self, count: int) -> None:
        assert should_recite(count, cadence=5) is False

    @pytest.mark.parametrize("count", [5, 10, 15, 20])
    def test_every_nth_turn_recites(self, count: int) -> None:
        assert should_recite(count, cadence=5) is True

    def test_default_cadence_matches_module_constant(self) -> None:
        assert should_recite(RECITATION_CADENCE) is True


class TestRecitationInputFilter_ByteIdenticalWhenOff:
    @pytest.mark.asyncio
    async def test_blank_plan_text_is_a_complete_no_op(self) -> None:
        f = RecitationInputFilter(plan_text="")
        messages = [_user("hello")]
        result_messages, result_prompt = await f.filter(messages, "system prompt")
        assert result_messages == messages
        assert result_prompt == "system prompt"

    @pytest.mark.asyncio
    async def test_whitespace_only_plan_text_is_a_complete_no_op(self) -> None:
        f = RecitationInputFilter(plan_text="   \n  ")
        messages = [_user("hello")]
        result_messages, _ = await f.filter(messages, "system prompt")
        assert result_messages == messages


class TestRecitationInputFilter_Cadence:
    @pytest.mark.asyncio
    async def test_first_human_turn_injects_full_plan(self) -> None:
        f = RecitationInputFilter(plan_text="FULL_PLAN_TEXT_MARKER")
        messages = [_user("hello")]
        result_messages, _ = await f.filter(messages, "sys")
        assert len(result_messages) == 2
        assert "FULL_PLAN_TEXT_MARKER" in result_messages[-1].content
        assert result_messages[-1].role == "user"

    @pytest.mark.asyncio
    async def test_non_cadence_human_turn_count_does_not_inject(self) -> None:
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        messages = [_user(), _assistant(), _tool(), _user(), _assistant(), _tool()]
        result_messages, _ = await f.filter(messages, "sys")
        assert result_messages == messages  # unchanged -- 2 human turns, not cadence

    @pytest.mark.asyncio
    async def test_fifth_human_turn_injects_recitation(self) -> None:
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        messages = [_user() for _ in range(5)]
        result_messages, _ = await f.filter(messages, "sys")
        assert len(result_messages) == 6
        assert "PLAN_TEXT_MARKER" in result_messages[-1].content

    @pytest.mark.asyncio
    async def test_five_tool_rounds_in_a_row_never_inject(self) -> None:
        """(DoD red-proof) Five SEPARATE tool-round continuations (e.g. a
        crash-resumed run() re-invoking input_filters without any NEW human
        message arriving) must NOT trigger recitation -- a NAIVE counter that
        increments on every filter() call (rather than deriving strictly from
        message history) would drift from 4 through 5..9 over these 5 calls
        and incorrectly fire the moment it crossed 5. The message-history-
        derived count stays at 4 (not a cadence hit) the whole time."""
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        # 4 genuine human turns already in history -- NOT a cadence hit (4 %
        # 5 != 0, 4 != 1) -- deliberately NOT count==1, so this test is
        # independent of the "first turn always recites" special case.
        messages: list[Message] = [_user() for _ in range(4)]
        assert count_human_turns(messages) == 4
        for _ in range(5):
            # Simulates a separate tool-round continuation: only
            # assistant/tool messages get appended between filter() calls,
            # exactly like a crash-resumed run() with no new user input.
            messages = [*messages, _assistant(), _tool()]
            result_messages, _ = await f.filter(messages, "sys")
            assert result_messages == messages, (
                "recitation must not fire during tool-round-only continuations"
            )
            assert count_human_turns(messages) == 4  # never advances

    @pytest.mark.asyncio
    async def test_full_text_on_first_sparse_text_thereafter(self) -> None:
        f = RecitationInputFilter(
            plan_text="FULL_TEXT_MARKER",
            plan_summary_text="SPARSE_TEXT_MARKER",
        )
        first_messages, _ = await f.filter([_user()], "sys")
        assert "FULL_TEXT_MARKER" in first_messages[-1].content
        assert "SPARSE_TEXT_MARKER" not in first_messages[-1].content

        fifth_messages, _ = await f.filter([_user() for _ in range(5)], "sys")
        assert "SPARSE_TEXT_MARKER" in fifth_messages[-1].content
        assert "FULL_TEXT_MARKER" not in fifth_messages[-1].content

    @pytest.mark.asyncio
    async def test_no_summary_text_falls_back_to_full_text(self) -> None:
        """plan_summary_text is optional -- degrades gracefully to the full
        text on cadence turns when the caller doesn't supply a sparse variant."""
        f = RecitationInputFilter(plan_text="ONLY_TEXT_MARKER")
        fifth_messages, _ = await f.filter([_user() for _ in range(5)], "sys")
        assert "ONLY_TEXT_MARKER" in fifth_messages[-1].content


class TestRecitationInputFilter_TailInjectionAndPrefixStability:
    @pytest.mark.asyncio
    async def test_recitation_is_the_last_message(self) -> None:
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        messages = [_user("q1"), _assistant("a1"), _tool("r1")]
        result_messages, _ = await f.filter(messages, "sys")
        assert result_messages[:-1] == messages  # prefix untouched, appended at tail
        assert "PLAN_TEXT_MARKER" in result_messages[-1].content

    @pytest.mark.asyncio
    async def test_does_not_mutate_input_messages_list(self) -> None:
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        messages = [_user("q1")]
        original_len = len(messages)
        await f.filter(messages, "sys")
        assert len(messages) == original_len  # caller's list untouched

    @pytest.mark.asyncio
    async def test_system_prompt_byte_identical_regardless_of_recitation(
        self,
    ) -> None:
        """(#2, joint test with Stage 1): recitation NEVER touches the static
        system prompt -- it is the volatile part (Stage 1's stable-prefix
        invariant) that must never carry the plan."""
        stable_system_prompt = build_stable_prefix(
            "You are a helpful assistant.", "user likes concise answers"
        )
        f = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")

        # Turn 1 (recites) and turn 2 (does not) -- system_prompt identical either way.
        _, prompt_on_recite = await f.filter([_user()], stable_system_prompt)
        _, prompt_off_cadence = await f.filter(
            [_user(), _assistant(), _tool(), _user()], stable_system_prompt
        )
        assert prompt_on_recite == stable_system_prompt
        assert prompt_off_cadence == stable_system_prompt
        assert prompt_on_recite == prompt_off_cadence


class TestRecitationInputFilter_RestartRecovery:
    @pytest.mark.asyncio
    async def test_fresh_filter_instance_reproduces_identical_cadence_decision(
        self,
    ) -> None:
        """(#3, DoD) The cadence counter is a PURE derivative of `messages` --
        never separate persisted state. A crash/restart that re-creates the
        filter from scratch, given the SAME history (as reloaded by the
        caller), reproduces the IDENTICAL recitation decision -- there is
        nothing else to restore."""
        messages = [_user() for _ in range(5)]

        filter_before_restart = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        before_messages, _ = await filter_before_restart.filter(messages, "sys")

        # Simulates process restart: a BRAND NEW filter instance, zero
        # constructor state carried over, given the SAME caller-persisted history.
        filter_after_restart = RecitationInputFilter(plan_text="PLAN_TEXT_MARKER")
        after_messages, _ = await filter_after_restart.filter(messages, "sys")

        assert after_messages == before_messages


class _FinalOnlyLlm:
    """Mock LLM: always answers with the final envelope (no tool calls)."""

    def __init__(self, text: str) -> None:
        self._raw = json.dumps({"type": "final", "final_message": text})

    async def __call__(self, messages, prompt, **kwargs):
        return self._raw


class TestRecitationInputFilter_EphemeralAcrossNewMessages:
    """(Hardening, pre-judge -- team-lead + codex round 1): the self-poisoning
    concern made concrete as a red-first end-to-end proof, not just "closed
    by reading the code". Recitation text injected into `messages`/
    `lm_messages` for THIS call of ``run_react()`` must NEVER surface in
    ``new_messages``/``RuntimeEvent.final`` -- the only channel a caller uses
    to persist history for a FUTURE call. If it did, ``count_human_turns()``
    would double-count recitations as human turns on every subsequent run(),
    drifting the cadence and breaking crash-restart recoverability.
    """

    @pytest.mark.asyncio
    async def test_recitation_never_appears_in_new_messages(self) -> None:
        # Cadence-triggering history (5 human turns): recitation WILL fire.
        f = RecitationInputFilter(plan_text="UNIQUE_RECITATION_MARKER_XYZ")
        messages = [_user() for _ in range(5)]
        filtered_messages, system_prompt = await f.filter(messages, "sys")

        # Sanity: the filter actually injected something this call -- a
        # trivially-passing test (nothing injected at all) would prove nothing.
        assert any(
            "UNIQUE_RECITATION_MARKER_XYZ" in m.content for m in filtered_messages
        )
        assert len(filtered_messages) == len(messages) + 1

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:google/gemini-3.5-flash",
            max_iterations=4,
            max_tool_calls=8,
        )
        executor = ToolExecutor(local_tools={})
        llm = _FinalOnlyLlm("done")

        events = []
        async for ev in run_react(
            llm,
            executor,
            messages=filtered_messages,
            system_prompt=system_prompt,
            tools=[],
            config=config,
            start_time=time.monotonic(),
        ):
            events.append(ev)

        final_events = [e for e in events if e.type == "final"]
        assert final_events, "run_react() never produced a final event"
        new_messages = final_events[0].data["new_messages"]
        joined = " ".join(str(m.get("content", "")) for m in new_messages)
        assert "UNIQUE_RECITATION_MARKER_XYZ" not in joined, (
            "recitation text leaked into new_messages -- this would let it "
            "re-enter a FUTURE run()'s messages parameter and inflate "
            "count_human_turns(), drifting the cadence"
        )
