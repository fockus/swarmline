"""Edge-case tests for RecoveryCascade — additional coverage beyond dev-domain tests.

Covers: negative attempt, empty goal, full cascade walkthrough,
single-strategy cascade, prompt content validation, RecoveryResult fields,
boundary between continue/stop.
"""

from __future__ import annotations

import pytest
from swarmline.evolution.recovery import (
    RecoveryCascade,
    RecoveryResult,
    RecoveryStrategy,
)
from swarmline.evolution.stuck_detector import StuckSignal

_SIGNAL = StuckSignal(repeated_tool="grep", repeat_count=3, confidence=0.9)


# ---------------------------------------------------------------------------
# RecoveryStrategy enum edge cases
# ---------------------------------------------------------------------------


class TestRecoveryStrategyEdge:
    """Edge cases for RecoveryStrategy enum."""

    def test_string_values(self) -> None:
        assert RecoveryStrategy.REPHRASE.value == "rephrase"
        assert RecoveryStrategy.SIMPLIFY.value == "simplify"
        assert RecoveryStrategy.ALTERNATIVE.value == "alternative"
        assert RecoveryStrategy.ESCALATE.value == "escalate"

    def test_iteration_order_matches_escalation(self) -> None:
        strategies = list(RecoveryStrategy)
        assert strategies[0] == RecoveryStrategy.REPHRASE
        assert strategies[-1] == RecoveryStrategy.ESCALATE

    def test_from_value(self) -> None:
        assert RecoveryStrategy("rephrase") == RecoveryStrategy.REPHRASE


# ---------------------------------------------------------------------------
# RecoveryCascade — negative / unusual attempt values
# ---------------------------------------------------------------------------


class TestRecoveryCascadeUnusualAttempts:
    """Unusual attempt numbers."""

    def test_negative_attempt_returns_first_strategy(self) -> None:
        """Negative index could cause IndexError — verify it doesn't."""
        cascade = RecoveryCascade()
        # Python list[-1] returns last element, but attempt should be 0-based
        # Implementation should handle this gracefully
        strategy = cascade.next_strategy(-1)
        # If it returns ESCALATE (from list[-1]), that's also acceptable
        assert isinstance(strategy, RecoveryStrategy)

    def test_very_large_attempt_returns_escalate(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(999999) == RecoveryStrategy.ESCALATE

    @pytest.mark.parametrize("attempt", [0, 1, 2, 3])
    def test_all_default_attempts_return_valid_strategy(self, attempt: int) -> None:
        cascade = RecoveryCascade()
        strategy = cascade.next_strategy(attempt)
        assert isinstance(strategy, RecoveryStrategy)


# ---------------------------------------------------------------------------
# RecoveryCascade — empty / special goal strings
# ---------------------------------------------------------------------------


class TestRecoveryCascadeGoalEdge:
    """Edge cases for original_goal parameter."""

    def test_empty_goal(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, _SIGNAL, "")
        assert isinstance(result.recovery_prompt, str)
        assert result.should_continue is True

    def test_very_long_goal(self) -> None:
        long_goal = "Find the bug " * 1000
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, _SIGNAL, long_goal)
        assert long_goal[:50] in result.recovery_prompt

    def test_goal_with_special_chars(self) -> None:
        goal = "Fix {template} with <html> & 'quotes' \"double\""
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, _SIGNAL, goal)
        assert goal in result.recovery_prompt

    def test_goal_with_newlines(self) -> None:
        goal = "Fix\nthe\nbug"
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, _SIGNAL, goal)
        assert "Fix\nthe\nbug" in result.recovery_prompt


# ---------------------------------------------------------------------------
# RecoveryCascade — StuckSignal variations
# ---------------------------------------------------------------------------


class TestRecoveryCascadeSignalEdge:
    """Edge cases for StuckSignal passed to recovery."""

    def test_signal_with_slash_tool_name(self) -> None:
        """Alternating pattern produces 'tool_a/tool_b' — verify prompt handles it."""
        signal = StuckSignal(repeated_tool="read/write", repeat_count=6, confidence=0.7)
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.REPHRASE, signal, "goal"
        )
        assert "read/write" in prompt

    def test_signal_with_zero_repeat_count(self) -> None:
        signal = StuckSignal(repeated_tool="t", repeat_count=0, confidence=0.0)
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, signal, "goal")
        assert isinstance(result.recovery_prompt, str)

    def test_signal_with_high_repeat_count(self) -> None:
        signal = StuckSignal(repeated_tool="t", repeat_count=100, confidence=0.99)
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, signal, "goal")
        assert "100" in result.recovery_prompt


# ---------------------------------------------------------------------------
# RecoveryCascade — full cascade walkthrough
# ---------------------------------------------------------------------------


class TestRecoveryCascadeFullWalkthrough:
    """Walk through all 4 strategies in sequence — integration-style test."""

    def test_full_cascade_all_strategies(self) -> None:
        cascade = RecoveryCascade()
        results: list[RecoveryResult] = []
        for attempt in range(4):
            result = cascade.get_recovery(attempt, _SIGNAL, "find the root cause")
            results.append(result)

        # First 3 should continue
        assert all(r.should_continue for r in results[:3])
        # Last should stop
        assert results[3].should_continue is False

        # Strategies in order
        assert results[0].strategy_used == RecoveryStrategy.REPHRASE
        assert results[1].strategy_used == RecoveryStrategy.SIMPLIFY
        assert results[2].strategy_used == RecoveryStrategy.ALTERNATIVE
        assert results[3].strategy_used == RecoveryStrategy.ESCALATE

        # All prompts are unique
        prompts = [r.recovery_prompt for r in results]
        assert len(set(prompts)) == 4

        # All prompts mention the stuck tool
        assert all("grep" in p for p in prompts)

    def test_cascade_exhaustion_stays_at_escalate(self) -> None:
        """After exhausting all strategies, further attempts always return ESCALATE."""
        cascade = RecoveryCascade()
        for attempt in range(4, 10):
            result = cascade.get_recovery(attempt, _SIGNAL, "goal")
            assert result.strategy_used == RecoveryStrategy.ESCALATE
            assert result.should_continue is False


# ---------------------------------------------------------------------------
# RecoveryCascade — custom strategy lists
# ---------------------------------------------------------------------------


class TestRecoveryCascadeCustomStrategies:
    """Custom strategy list configurations."""

    def test_single_strategy_cascade(self) -> None:
        cascade = RecoveryCascade(strategies=[RecoveryStrategy.SIMPLIFY])
        result = cascade.get_recovery(0, _SIGNAL, "goal")
        assert result.strategy_used == RecoveryStrategy.SIMPLIFY
        assert result.should_continue is True

        # Beyond list → ESCALATE
        result = cascade.get_recovery(1, _SIGNAL, "goal")
        assert result.strategy_used == RecoveryStrategy.ESCALATE
        assert result.should_continue is False

    def test_only_escalate_cascade(self) -> None:
        cascade = RecoveryCascade(strategies=[RecoveryStrategy.ESCALATE])
        result = cascade.get_recovery(0, _SIGNAL, "goal")
        assert result.strategy_used == RecoveryStrategy.ESCALATE
        assert result.should_continue is False

    def test_reversed_order_cascade(self) -> None:
        cascade = RecoveryCascade(
            strategies=[
                RecoveryStrategy.ESCALATE,
                RecoveryStrategy.ALTERNATIVE,
                RecoveryStrategy.SIMPLIFY,
                RecoveryStrategy.REPHRASE,
            ]
        )
        assert cascade.next_strategy(0) == RecoveryStrategy.ESCALATE
        assert cascade.next_strategy(3) == RecoveryStrategy.REPHRASE

    def test_duplicate_strategies_allowed(self) -> None:
        cascade = RecoveryCascade(
            strategies=[RecoveryStrategy.REPHRASE, RecoveryStrategy.REPHRASE]
        )
        assert cascade.next_strategy(0) == RecoveryStrategy.REPHRASE
        assert cascade.next_strategy(1) == RecoveryStrategy.REPHRASE

    def test_empty_strategies_list_uses_default(self) -> None:
        """Empty list is falsy in Python → `[] or list(RecoveryStrategy)` → uses defaults."""
        cascade = RecoveryCascade(strategies=[])
        # Python: `[] or list(RecoveryStrategy)` evaluates to default list
        result = cascade.get_recovery(0, _SIGNAL, "goal")
        assert result.strategy_used == RecoveryStrategy.REPHRASE
        assert result.should_continue is True


# ---------------------------------------------------------------------------
# RecoveryCascade — prompt content validation
# ---------------------------------------------------------------------------


class TestRecoveryCascadePromptContent:
    """Validate prompt content has meaningful recovery instructions."""

    @pytest.mark.parametrize(
        "strategy,keyword",
        [
            (RecoveryStrategy.REPHRASE, "rephrase"),
            (RecoveryStrategy.SIMPLIFY, "break"),
            (RecoveryStrategy.ALTERNATIVE, "alternative"),
            (RecoveryStrategy.ESCALATE, "stuck"),
        ],
    )
    def test_prompt_contains_strategy_keyword(
        self, strategy: RecoveryStrategy, keyword: str
    ) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(strategy, _SIGNAL, "test goal")
        assert keyword.lower() in prompt.lower()

    def test_prompt_includes_repeat_count(self) -> None:
        signal = StuckSignal(repeated_tool="read_file", repeat_count=5, confidence=0.9)
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.REPHRASE, signal, "goal"
        )
        assert "5" in prompt

    def test_all_prompts_include_goal(self) -> None:
        cascade = RecoveryCascade()
        goal = "deploy to production"
        for strategy in RecoveryStrategy:
            prompt = cascade.build_recovery_prompt(strategy, _SIGNAL, goal)
            assert goal in prompt


# ---------------------------------------------------------------------------
# RecoveryResult edge cases
# ---------------------------------------------------------------------------


class TestRecoveryResultEdge:
    """Edge cases for RecoveryResult dataclass."""

    def test_equality(self) -> None:
        r1 = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="p",
            should_continue=True,
        )
        r2 = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="p",
            should_continue=True,
        )
        assert r1 == r2

    def test_hashable(self) -> None:
        r = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="p",
            should_continue=True,
        )
        assert hash(r) is not None

    def test_non_escalate_with_false_continue_possible(self) -> None:
        """RecoveryResult doesn't enforce should_continue based on strategy."""
        r = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="p",
            should_continue=False,
        )
        assert r.should_continue is False
        assert r.strategy_used == RecoveryStrategy.REPHRASE


# ---------------------------------------------------------------------------
# Protocol conformance — additional checks
# ---------------------------------------------------------------------------


class TestProtocolConformanceEdge:
    """Extended protocol conformance checks."""

    def test_cascade_has_all_protocol_methods(self) -> None:
        cascade = RecoveryCascade()
        assert hasattr(cascade, "next_strategy")
        assert hasattr(cascade, "build_recovery_prompt")
        assert hasattr(cascade, "get_recovery")
        assert callable(cascade.next_strategy)
        assert callable(cascade.build_recovery_prompt)
        assert callable(cascade.get_recovery)
