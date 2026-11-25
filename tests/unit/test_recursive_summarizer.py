"""Tests for RecursiveSummarizer — code-aware recursive history compression.

REQ-RCA-020 / G4: WHEN context exceeds its budget, compress history via
recursive summarization that splits at an assistant-message boundary and
preserves file paths, stack traces, and symbol names in the summary.

TDD: tests written before implementation.
"""

from __future__ import annotations

import pytest

from swarmline.context.budget import estimate_tokens
from swarmline.memory.recursive_summary import (
    RecursiveSummarizer,
    _find_assistant_split_point,
)
from swarmline.memory.types import MemoryMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str) -> MemoryMessage:
    return MemoryMessage(role=role, content=content)


def _total_tokens(messages: list[MemoryMessage]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


def _make_large_history(n: int = 20, chars_per_msg: int = 400) -> list[MemoryMessage]:
    """Alternating user/assistant messages, each with substantial content."""
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(_msg(role, f"message {i}: " + "x" * chars_per_msg))
    return messages


# ---------------------------------------------------------------------------
# 1. Within-budget history → no LLM call, returned unchanged
# ---------------------------------------------------------------------------


class TestWithinBudget:
    @pytest.mark.asyncio
    async def test_within_budget_returns_unchanged_no_llm_call(self) -> None:
        """History within budget: no LLM call and messages returned unchanged."""
        call_count = 0

        async def spy_llm(prompt: str, dialog: str) -> str:
            nonlocal call_count
            call_count += 1
            return "summary"

        messages = [
            _msg("user", "Hello"),
            _msg("assistant", "Hi there"),
        ]
        total = _total_tokens(messages)
        budget = total + 1000  # well within budget

        summarizer = RecursiveSummarizer(spy_llm, token_budget=budget)
        result = await summarizer.asummarize(messages)

        assert result == messages
        assert call_count == 0


# ---------------------------------------------------------------------------
# 2. Over-budget history compresses to below budget
# ---------------------------------------------------------------------------


class TestOverBudgetCompression:
    @pytest.mark.asyncio
    async def test_over_budget_history_compresses_below_budget(self) -> None:
        """Large history compressed until token count drops below budget."""

        async def compact_llm(prompt: str, dialog: str) -> str:
            return "Compact summary."  # small output, ~5 tokens

        messages = _make_large_history(n=20, chars_per_msg=400)
        initial_tokens = _total_tokens(messages)
        budget = 500  # achievable in ≤3 recursion steps

        assert initial_tokens > budget, "pre-condition: history must be over-budget"

        summarizer = RecursiveSummarizer(compact_llm, token_budget=budget)
        result = await summarizer.asummarize(messages)

        result_tokens = _total_tokens(result)
        assert result_tokens <= budget


# ---------------------------------------------------------------------------
# 3. Split always ends on an assistant-message boundary
# ---------------------------------------------------------------------------


class TestAssistantBoundarySplit:
    """_find_assistant_split_point returns a split where messages[split-1].role == 'assistant'."""

    @pytest.mark.parametrize(
        "roles,midpoint,expected_role",
        [
            # Normal alternation — split lands exactly on the assistant
            (["user", "assistant", "user", "assistant"], 2, "assistant"),
            # Three-message history — midpoint 2 → messages[1].role == 'assistant'
            (["user", "assistant", "user"], 2, "assistant"),
            # Extra user messages after midpoint — walk back to find assistant
            (["user", "assistant", "user", "user", "user"], 3, "assistant"),
        ],
    )
    def test_split_point_role_at_split_minus_1(
        self, roles: list[str], midpoint: int, expected_role: str
    ) -> None:
        messages = [_msg(r, f"content {i}") for i, r in enumerate(roles)]
        split = _find_assistant_split_point(messages, midpoint)
        assert 1 <= split <= len(messages)
        assert messages[split - 1].role == expected_role

    @pytest.mark.parametrize(
        "roles",
        [
            # F1 regression: old code returned split=1 (HEAD=[user]) for both — TORN pair
            ["user", "assistant"],  # midpoint=1 → backward miss → forward finds split=2
            [
                "user",
                "assistant",
                "user",
            ],  # midpoint=1 → backward miss → forward finds split=2
            # No assistant anywhere: split must equal len (summarise all)
            ["user"],  # midpoint=0 → no assistant → split=len=1
            ["user", "user"],  # midpoint=1 → no assistant → split=len=2
            # Longer odd histories — still invariant holds
            [
                "user",
                "assistant",
                "user",
                "assistant",
                "user",
            ],  # midpoint=2 → backward finds split=2
            [
                "user",
                "user",
                "user",
                "assistant",
                "user",
            ],  # midpoint=2 → forward finds split=4
        ],
    )
    def test_split_invariant_with_production_midpoint_various_histories(
        self, roles: list[str]
    ) -> None:
        """Invariant: messages[split-1].role=='assistant' OR split==len(messages).

        This test FAILS against the old fallback (max(1,midpoint)) for
        [user,assistant], [user,assistant,user], [user,user] and the forward-search
        case — and PASSES after the F1 fix.
        """
        messages = [_msg(r, f"content {i}") for i, r in enumerate(roles)]
        midpoint = len(messages) // 2  # production value
        split = _find_assistant_split_point(messages, midpoint)

        is_on_assistant = split > 0 and messages[split - 1].role == "assistant"
        is_summarise_all = split == len(messages)

        split_role = messages[split - 1].role if split <= len(messages) else "N/A"
        assert is_on_assistant or is_summarise_all, (
            f"roles={roles}, midpoint={midpoint}, split={split}, "
            f"split-1 role={split_role!r}"
        )

    @pytest.mark.asyncio
    async def test_recursive_summarizer_compresses_over_budget_alternating_history(
        self,
    ) -> None:
        """Integration: over-budget alternating history gets compressed (LLM called)."""
        call_count = 0

        async def recording_llm(prompt: str, dialog: str) -> str:
            nonlocal call_count
            call_count += 1
            return "Short summary."

        messages = [
            _msg("user", "q1 " * 80),
            _msg("assistant", "a1 " * 80),
            _msg("user", "q2 " * 80),
            _msg("assistant", "a2 " * 80),
        ]

        budget = 20  # far below history size → force compression
        summarizer = RecursiveSummarizer(recording_llm, token_budget=budget)
        result = await summarizer.asummarize(messages)

        assert call_count >= 1, "Expected at least one LLM call"
        assert result, "Expected non-empty result"


# ---------------------------------------------------------------------------
# 4. Recursion is bounded at depth 3 (≤3 LLM calls)
# ---------------------------------------------------------------------------


class TestRecursionBound:
    @pytest.mark.asyncio
    async def test_recursion_bounded_at_depth_3_pathological_input(self) -> None:
        """Even when LLM always returns a huge summary, recursion stops at depth 3."""
        call_count = 0

        async def always_large_llm(prompt: str, dialog: str) -> str:
            nonlocal call_count
            call_count += 1
            return (
                "HUGE " * 500
            )  # ~625 tokens; always keeps result over any tiny budget

        messages = _make_large_history(n=30, chars_per_msg=400)
        budget = 10  # impossibly small budget

        summarizer = RecursiveSummarizer(always_large_llm, token_budget=budget)
        result = await summarizer.asummarize(messages)

        assert call_count <= 3, f"Expected ≤3 LLM calls but got {call_count}"
        assert result, "Must return a non-empty result (best-effort)"


# ---------------------------------------------------------------------------
# 5. Code anchors preserved in summary prompt and dialog
# ---------------------------------------------------------------------------


class TestCodeAwarePrompt:
    @pytest.mark.asyncio
    async def test_summary_retains_code_anchors_in_prompt_and_dialog(self) -> None:
        """Code-aware instruction is in prompt; anchors survive into the compressed OUTPUT.

        The fake LLM echoes back anchors it finds in the dialog so we can verify
        end-to-end propagation: anchor → dialog → LLM output → summary message →
        final result list content.  This test fails if the LLM discards anchors
        (old "Short summary." fake) and passes only when the output truly preserves them.
        """
        captured: list[tuple[str, str]] = []

        file_path = "src/foo/bar.py"
        symbol = "MyClass.do_work"
        anchors = [file_path, symbol, "ValueError"]

        async def anchor_preserving_llm(prompt: str, dialog_text: str) -> str:
            captured.append((prompt, dialog_text))
            # Echo back every anchor found in the dialog so they propagate forward
            found = [a for a in anchors if a in dialog_text]
            return f"Code review summary. Preserved refs: {'; '.join(found)}."

        stack_trace = (
            '  File "src/foo/bar.py", line 42, in do_work\nValueError: unexpected None'
        )

        # Anchor messages first so they land in HEAD when split at midpoint
        anchor_messages: list[MemoryMessage] = [
            _msg("user", f"What is wrong with {file_path}?"),
            _msg("assistant", f"Error in {symbol}:\n{stack_trace}"),
        ]
        # Padding to make total tokens >> budget
        pad: list[MemoryMessage] = [
            _msg("user" if i % 2 == 0 else "assistant", f"padding msg {i} " * 60)
            for i in range(10)
        ]
        messages = anchor_messages + pad

        budget = 20  # tiny → forces compression
        summarizer = RecursiveSummarizer(anchor_preserving_llm, token_budget=budget)
        result = await summarizer.asummarize(messages)

        assert len(captured) >= 1, "LLM should have been called at least once"

        all_prompts = " ".join(p for p, _ in captured)
        all_dialogs = " ".join(d for _, d in captured)

        # 1. Code-aware instruction in the system prompt
        assert any(
            kw in all_prompts.lower() for kw in ("file path", "stack trace", "symbol")
        ), f"Code-aware instruction missing from prompts. Got: {all_prompts[:400]!r}"

        # 2. Anchors present in at least one dialog (HEAD always contains anchor messages
        #    on the first call, since anchor_messages are at the front of the list)
        assert file_path in all_dialogs, f"file_path {file_path!r} not in any dialog"
        assert symbol in all_dialogs, f"symbol {symbol!r} not in any dialog"
        assert "ValueError" in all_dialogs, (
            "'ValueError' (stack trace) not in any dialog"
        )

        # 3. Anchors present in the FINAL compressed output (end-to-end preservation).
        #    The anchor_preserving_llm echoes them into the summary message; subsequent
        #    rounds receive that summary in HEAD and echo them again — so anchors survive.
        all_result_content = " ".join(msg.content for msg in result)
        assert file_path in all_result_content, (
            f"file_path {file_path!r} lost from final compressed output"
        )
        assert symbol in all_result_content, (
            f"symbol {symbol!r} lost from final compressed output"
        )
        assert "ValueError" in all_result_content, (
            "'ValueError' (stack trace) lost from final compressed output"
        )


# ---------------------------------------------------------------------------
# 6. Token counting goes through context/budget.estimate_tokens
# ---------------------------------------------------------------------------


class TestTokenCountingViaContextBudget:
    def test_estimate_tokens_re_exported_from_context_budget(self) -> None:
        """RecursiveSummarizer uses the same estimate_tokens as context.budget."""
        from swarmline.memory.recursive_summary import estimate_tokens as rs_et
        from swarmline.context.budget import estimate_tokens as cb_et

        assert rs_et is cb_et  # same function object — not a private re-implementation

    @pytest.mark.asyncio
    async def test_budget_threshold_matches_estimate_tokens_from_context_budget(
        self,
    ) -> None:
        """Compression triggers at the exact token count computed by estimate_tokens."""
        call_count = 0

        async def spy_llm(prompt: str, dialog: str) -> str:
            nonlocal call_count
            call_count += 1
            return "summary"

        content = "x" * 400  # estimate_tokens("x"*400) = 400//4+1 = 101 tokens
        messages = [
            _msg("user", content),
            _msg("assistant", content),
        ]
        exact_tokens = sum(estimate_tokens(m.content) for m in messages)  # 202 tokens

        # Budget one below exact → must trigger compression
        summarizer_low = RecursiveSummarizer(spy_llm, token_budget=exact_tokens - 1)
        await summarizer_low.asummarize(messages)
        assert call_count >= 1, "Should have compressed: history is over budget"

        # Budget at exact count → must NOT trigger compression
        call_count = 0
        summarizer_exact = RecursiveSummarizer(spy_llm, token_budget=exact_tokens)
        await summarizer_exact.asummarize(messages)
        assert call_count == 0, "Should NOT compress: history is within budget"


# ---------------------------------------------------------------------------
# 7. LlmSummaryGenerator public contract backward compat
# ---------------------------------------------------------------------------


class TestLlmSummaryGeneratorBackwardCompat:
    @pytest.mark.asyncio
    async def test_asummarize_without_token_budget_works_as_before(self) -> None:
        """Existing callers without token_budget still get a str summary."""

        async def fake_llm(prompt: str, dialog: str) -> str:
            return "Краткое резюме разговора. " * 5

        from swarmline.memory.llm_summarizer import LlmSummaryGenerator

        gen = LlmSummaryGenerator(llm_call=fake_llm)
        messages = [_msg("user", "Hello"), _msg("assistant", "Hi")]
        result = await gen.asummarize(messages)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_asummarize_with_token_budget_delegates_to_recursive_summarizer(
        self,
    ) -> None:
        """With token_budget, asummarize uses RecursiveSummarizer (LLM is called)."""
        call_count = 0

        async def counting_llm(prompt: str, dialog: str) -> str:
            nonlocal call_count
            call_count += 1
            return "Small summary."

        from swarmline.memory.llm_summarizer import LlmSummaryGenerator

        gen = LlmSummaryGenerator(llm_call=counting_llm, token_budget=5)
        messages = _make_large_history(n=10, chars_per_msg=200)
        result = await gen.asummarize(messages)

        assert isinstance(result, str)
        assert call_count >= 1, "RecursiveSummarizer should have called the LLM"

    @pytest.mark.asyncio
    async def test_asummarize_no_llm_no_budget_falls_back_to_template(self) -> None:
        """No llm_call and no token_budget → template fallback (regression)."""
        from swarmline.memory.llm_summarizer import LlmSummaryGenerator

        gen = LlmSummaryGenerator(llm_call=None)
        messages = [_msg("user", "Hello"), _msg("assistant", "Hi")]
        result = await gen.asummarize(messages)

        assert isinstance(result, str)
        assert "Hello" in result or "Hi" in result
