"""Unit: complexity classifier — TaskComplexity enum, ComplexityBudget, classify(), get_budget().

REQ-OSS-060: swarmline-native primitive, zero product coupling.
"""

from __future__ import annotations

import pytest

from swarmline.routing.complexity import (
    ComplexityBudget,
    TaskComplexity,
    TaskComplexityClassifier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _words(n: int) -> str:
    """Return a plain prompt of exactly *n* whitespace-separated tokens."""
    return " ".join(["word"] * n)


# ---------------------------------------------------------------------------
# TaskComplexity enum
# ---------------------------------------------------------------------------


class TestTaskComplexityEnum:
    """StrEnum values are lowercase strings."""

    def test_simple_value_is_simple_string(self) -> None:
        assert TaskComplexity.SIMPLE == "simple"

    def test_medium_value_is_medium_string(self) -> None:
        assert TaskComplexity.MEDIUM == "medium"

    def test_complex_value_is_complex_string(self) -> None:
        assert TaskComplexity.COMPLEX == "complex"


# ---------------------------------------------------------------------------
# ComplexityBudget dataclass
# ---------------------------------------------------------------------------


class TestComplexityBudget:
    """Frozen dataclass — direct construction and immutability."""

    def test_construction_stores_all_fields(self) -> None:
        budget = ComplexityBudget(
            max_turns=5, planning_required=True, scratchpad_recommended=False
        )
        assert budget.max_turns == 5
        assert budget.planning_required is True
        assert budget.scratchpad_recommended is False

    def test_budget_is_frozen_cannot_mutate(self) -> None:
        budget = ComplexityBudget(
            max_turns=3, planning_required=False, scratchpad_recommended=False
        )
        with pytest.raises((AttributeError, TypeError)):
            budget.max_turns = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TaskComplexityClassifier.classify() — core routing
# ---------------------------------------------------------------------------


class TestClassifyBuckets:
    """Core routing into COMPLEX / MEDIUM / SIMPLE."""

    clf = TaskComplexityClassifier()

    # -- COMPLEX --

    def test_classify_long_prompt_many_tools_returns_complex(self) -> None:
        """201-word prompt + 6 tools → COMPLEX (word_count > 200 and tool_count > 5)."""
        assert self.clf.classify(_words(201), tool_count=6) is TaskComplexity.COMPLEX

    def test_classify_keyword_analyze_many_tools_returns_complex(self) -> None:
        """Short prompt with 'analyze' keyword + 6 tools → COMPLEX."""
        assert (
            self.clf.classify("analyze the system output", tool_count=6)
            is TaskComplexity.COMPLEX
        )

    def test_classify_keyword_plan_many_tools_returns_complex(self) -> None:
        """'plan' keyword drives is_complex_prompt; 7 tools → COMPLEX."""
        assert (
            self.clf.classify("plan the migration", tool_count=7)
            is TaskComplexity.COMPLEX
        )

    def test_classify_keyword_research_many_tools_returns_complex(self) -> None:
        assert (
            self.clf.classify("research competitor pricing", tool_count=8)
            is TaskComplexity.COMPLEX
        )

    # -- SIMPLE --

    def test_classify_short_plain_no_tools_returns_simple(self) -> None:
        """Short, no keywords, 0 tools → SIMPLE."""
        assert self.clf.classify("hello world", tool_count=0) is TaskComplexity.SIMPLE

    def test_classify_short_plain_3_tools_returns_simple(self) -> None:
        """tool_count == 3 (≤ 3) still satisfies the SIMPLE condition."""
        assert self.clf.classify("fix this bug", tool_count=3) is TaskComplexity.SIMPLE

    def test_classify_default_tool_count_is_zero_returns_simple(self) -> None:
        """tool_count defaults to 0 — SIMPLE for a clean short prompt."""
        assert self.clf.classify("rename the variable") is TaskComplexity.SIMPLE

    # -- MEDIUM --

    def test_classify_mid_length_no_keyword_no_tools_returns_medium(self) -> None:
        """100-word prompt, no keywords → not COMPLEX (tool_count ≤ 5), not SIMPLE → MEDIUM."""
        assert self.clf.classify(_words(100)) is TaskComplexity.MEDIUM

    def test_classify_keyword_but_tool_count_5_returns_medium(self) -> None:
        """'analyze' → is_complex_prompt=True, but tool_count=5 is NOT > 5 → MEDIUM."""
        assert self.clf.classify("analyze this", tool_count=5) is TaskComplexity.MEDIUM

    def test_classify_long_prompt_but_tool_count_5_returns_medium(self) -> None:
        """201 words → is_complex_prompt=True, but tool_count=5 ≤ 5 → MEDIUM."""
        assert self.clf.classify(_words(201), tool_count=5) is TaskComplexity.MEDIUM

    def test_classify_short_prompt_4_tools_returns_medium(self) -> None:
        """Short prompt, no keyword, but tool_count=4 > 3 → NOT SIMPLE → MEDIUM."""
        assert self.clf.classify("fix this bug", tool_count=4) is TaskComplexity.MEDIUM


# ---------------------------------------------------------------------------
# classify() — keyword coverage (all 7 keywords)
# ---------------------------------------------------------------------------


class TestClassifyKeywords:
    """Every configured keyword is detected (case-insensitive) and raises is_complex_prompt."""

    clf = TaskComplexityClassifier()

    @pytest.mark.parametrize(
        "keyword",
        [
            "plan",
            "analyze",
            "research",
            "compare",
            "multi-step",
            "report",
            "investigate",
        ],
    )
    def test_keyword_detected_with_many_tools_yields_complex(
        self, keyword: str
    ) -> None:
        """Each keyword triggers is_complex_prompt; combined with tool_count>5 → COMPLEX."""
        prompt = f"please {keyword} the data set"
        result = self.clf.classify(prompt, tool_count=6)
        assert result is TaskComplexity.COMPLEX, (
            f"keyword '{keyword}' should have set is_complex_prompt=True → COMPLEX, got {result}"
        )

    def test_keyword_matching_is_case_insensitive(self) -> None:
        """ANALYZE (upper-case) must be detected."""
        assert (
            self.clf.classify("ANALYZE everything deeply", tool_count=6)
            is TaskComplexity.COMPLEX
        )

    def test_keyword_must_match_whole_word(self) -> None:
        """'replan' does NOT contain the whole word 'plan'; must not trigger the keyword path."""
        # 'replan' — 'plan' is a suffix, not a whole word match
        # With only a 3-word prompt and ≤3 tools the result would be SIMPLE if keyword
        # is NOT detected; MEDIUM if it is accidentally detected.
        result = self.clf.classify("replan the schedule", tool_count=0)
        # 'research' / 'plan' / etc. are NOT matched inside 'replan' via \b boundary
        assert result is TaskComplexity.SIMPLE


# ---------------------------------------------------------------------------
# classify() — boundary values (exact thresholds)
# ---------------------------------------------------------------------------


class TestClassifyBoundaries:
    """Exact boundary checks at word_count = 200/201 and tool_count = 3/4/5/6."""

    clf = TaskComplexityClassifier()

    @pytest.mark.parametrize(
        "word_count, tool_count, expected",
        [
            # word_count boundary (no keywords)
            (201, 6, TaskComplexity.COMPLEX),  # > 200 AND > 5 → COMPLEX
            (
                200,
                6,
                TaskComplexity.MEDIUM,
            ),  # NOT > 200 → is_complex_prompt=False → MEDIUM
            (201, 5, TaskComplexity.MEDIUM),  # > 200 but tool_count not > 5 → MEDIUM
            (
                50,
                0,
                TaskComplexity.MEDIUM,
            ),  # NOT < 50 → is_simple_prompt=False → MEDIUM
            (49, 0, TaskComplexity.SIMPLE),  # < 50, no keyword, 0 tools → SIMPLE
            # tool_count boundary (short plain prompt)
            (10, 3, TaskComplexity.SIMPLE),  # tool_count == 3 (≤ 3) → SIMPLE
            (
                10,
                4,
                TaskComplexity.MEDIUM,
            ),  # tool_count == 4 (> 3) → NOT SIMPLE → MEDIUM
            (10, 5, TaskComplexity.MEDIUM),  # tool_count == 5 (not > 5) → MEDIUM
            (
                10,
                6,
                TaskComplexity.MEDIUM,
            ),  # tool_count == 6 but no is_complex_prompt → MEDIUM
        ],
    )
    def test_classify_boundary(
        self, word_count: int, tool_count: int, expected: TaskComplexity
    ) -> None:
        result = self.clf.classify(_words(word_count), tool_count=tool_count)
        assert result is expected, (
            f"word_count={word_count}, tool_count={tool_count}: "
            f"expected {expected!r}, got {result!r}"
        )


# ---------------------------------------------------------------------------
# get_budget() — exact field values
# ---------------------------------------------------------------------------


class TestGetBudget:
    """get_budget() returns the canonical frozen ComplexityBudget for each level."""

    clf = TaskComplexityClassifier()

    def test_get_budget_simple_has_3_turns_no_planning_no_scratchpad(self) -> None:
        budget = self.clf.get_budget(TaskComplexity.SIMPLE)
        assert budget.max_turns == 3
        assert budget.planning_required is False
        assert budget.scratchpad_recommended is False

    def test_get_budget_medium_has_7_turns_no_planning_with_scratchpad(self) -> None:
        budget = self.clf.get_budget(TaskComplexity.MEDIUM)
        assert budget.max_turns == 7
        assert budget.planning_required is False
        assert budget.scratchpad_recommended is True

    def test_get_budget_complex_has_15_turns_with_planning_with_scratchpad(
        self,
    ) -> None:
        budget = self.clf.get_budget(TaskComplexity.COMPLEX)
        assert budget.max_turns == 15
        assert budget.planning_required is True
        assert budget.scratchpad_recommended is True

    def test_get_budget_returns_frozen_budget_instance(self) -> None:
        """Budget objects must be frozen (dataclass frozen=True)."""
        budget = self.clf.get_budget(TaskComplexity.COMPLEX)
        with pytest.raises((AttributeError, TypeError)):
            budget.max_turns = 0  # type: ignore[misc]

    def test_get_budget_same_instance_each_call(self) -> None:
        """Budgets are module-level constants; same object identity expected."""
        b1 = self.clf.get_budget(TaskComplexity.SIMPLE)
        b2 = self.clf.get_budget(TaskComplexity.SIMPLE)
        assert b1 is b2
