"""Tests for RecoveryCascade — 4-strategy escalation.

TDD Red phase: all tests written before implementation.
Covers: cascade order, prompts, ESCALATE stops, RecoveryResult.
"""

from __future__ import annotations

import pytest
from swarmline.evolution.recovery import (
    RecoveryCascade,
    RecoveryCascadeLike,
    RecoveryResult,
    RecoveryStrategy,
)
from swarmline.evolution.stuck_detector import StuckSignal

# ---------------------------------------------------------------------------
# RecoveryStrategy enum
# ---------------------------------------------------------------------------


class TestRecoveryStrategy:
    """RecoveryStrategy enum tests."""

    def test_has_four_values(self) -> None:
        assert len(RecoveryStrategy) == 4

    def test_values_exist(self) -> None:
        assert RecoveryStrategy.REPHRASE is not None
        assert RecoveryStrategy.SIMPLIFY is not None
        assert RecoveryStrategy.ALTERNATIVE is not None
        assert RecoveryStrategy.ESCALATE is not None

    def test_default_order(self) -> None:
        expected = [
            RecoveryStrategy.REPHRASE,
            RecoveryStrategy.SIMPLIFY,
            RecoveryStrategy.ALTERNATIVE,
            RecoveryStrategy.ESCALATE,
        ]
        assert list(RecoveryStrategy) == expected


# ---------------------------------------------------------------------------
# RecoveryResult — frozen dataclass
# ---------------------------------------------------------------------------


class TestRecoveryResult:
    """RecoveryResult value object tests."""

    def test_frozen(self) -> None:
        result = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="try again",
            should_continue=True,
        )
        with pytest.raises(AttributeError):
            result.should_continue = False  # type: ignore[misc]

    def test_escalate_should_not_continue(self) -> None:
        result = RecoveryResult(
            strategy_used=RecoveryStrategy.ESCALATE,
            recovery_prompt="stuck",
            should_continue=False,
        )
        assert result.should_continue is False

    def test_non_escalate_should_continue(self) -> None:
        result = RecoveryResult(
            strategy_used=RecoveryStrategy.REPHRASE,
            recovery_prompt="rephrase",
            should_continue=True,
        )
        assert result.should_continue is True


# ---------------------------------------------------------------------------
# RecoveryCascade — Protocol conformance
# ---------------------------------------------------------------------------


class TestRecoveryCascadeProtocol:
    """Verify RecoveryCascade satisfies RecoveryCascadeLike protocol."""

    def test_implements_protocol(self) -> None:
        cascade = RecoveryCascade()
        assert isinstance(cascade, RecoveryCascadeLike)


# ---------------------------------------------------------------------------
# RecoveryCascade — cascade order
# ---------------------------------------------------------------------------


class TestRecoveryCascadeOrder:
    """Cascade returns strategies in order."""

    def test_attempt_0_is_rephrase(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(0) == RecoveryStrategy.REPHRASE

    def test_attempt_1_is_simplify(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(1) == RecoveryStrategy.SIMPLIFY

    def test_attempt_2_is_alternative(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(2) == RecoveryStrategy.ALTERNATIVE

    def test_attempt_3_is_escalate(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(3) == RecoveryStrategy.ESCALATE

    def test_attempt_beyond_last_returns_escalate(self) -> None:
        cascade = RecoveryCascade()
        assert cascade.next_strategy(10) == RecoveryStrategy.ESCALATE

    def test_custom_strategies_order(self) -> None:
        cascade = RecoveryCascade(
            strategies=[RecoveryStrategy.SIMPLIFY, RecoveryStrategy.ESCALATE]
        )
        assert cascade.next_strategy(0) == RecoveryStrategy.SIMPLIFY
        assert cascade.next_strategy(1) == RecoveryStrategy.ESCALATE


# ---------------------------------------------------------------------------
# RecoveryCascade — build_recovery_prompt
# ---------------------------------------------------------------------------


_STUCK_SIGNAL = StuckSignal(repeated_tool="grep", repeat_count=3, confidence=0.9)


class TestRecoveryCascadePrompts:
    """Each strategy produces a non-empty prompt containing the goal."""

    def test_rephrase_prompt_non_empty(self) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.REPHRASE, _STUCK_SIGNAL, "find the bug"
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "find the bug" in prompt

    def test_simplify_prompt_non_empty(self) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.SIMPLIFY, _STUCK_SIGNAL, "find the bug"
        )
        assert len(prompt) > 0
        assert "find the bug" in prompt

    def test_alternative_prompt_non_empty(self) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.ALTERNATIVE, _STUCK_SIGNAL, "find the bug"
        )
        assert len(prompt) > 0
        assert "find the bug" in prompt

    def test_escalate_prompt_non_empty(self) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.ESCALATE, _STUCK_SIGNAL, "find the bug"
        )
        assert len(prompt) > 0

    def test_prompt_includes_stuck_tool(self) -> None:
        cascade = RecoveryCascade()
        prompt = cascade.build_recovery_prompt(
            RecoveryStrategy.REPHRASE, _STUCK_SIGNAL, "find the bug"
        )
        assert "grep" in prompt

    def test_each_strategy_produces_different_prompt(self) -> None:
        cascade = RecoveryCascade()
        prompts = set()
        for strategy in RecoveryStrategy:
            prompt = cascade.build_recovery_prompt(strategy, _STUCK_SIGNAL, "goal")
            prompts.add(prompt)
        assert len(prompts) == 4


# ---------------------------------------------------------------------------
# RecoveryCascade — get_recovery (full flow)
# ---------------------------------------------------------------------------


class TestRecoveryCascadeGetRecovery:
    """get_recovery returns RecoveryResult with correct should_continue."""

    def test_attempt_0_should_continue(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(0, _STUCK_SIGNAL, "goal")
        assert result.should_continue is True
        assert result.strategy_used == RecoveryStrategy.REPHRASE
        assert len(result.recovery_prompt) > 0

    def test_attempt_1_should_continue(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(1, _STUCK_SIGNAL, "goal")
        assert result.should_continue is True
        assert result.strategy_used == RecoveryStrategy.SIMPLIFY

    def test_attempt_2_should_continue(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(2, _STUCK_SIGNAL, "goal")
        assert result.should_continue is True
        assert result.strategy_used == RecoveryStrategy.ALTERNATIVE

    def test_attempt_3_escalate_should_not_continue(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(3, _STUCK_SIGNAL, "goal")
        assert result.should_continue is False
        assert result.strategy_used == RecoveryStrategy.ESCALATE

    def test_attempt_beyond_max_escalates(self) -> None:
        cascade = RecoveryCascade()
        result = cascade.get_recovery(100, _STUCK_SIGNAL, "goal")
        assert result.should_continue is False
        assert result.strategy_used == RecoveryStrategy.ESCALATE

    def test_custom_cascade_with_no_escalate(self) -> None:
        cascade = RecoveryCascade(
            strategies=[RecoveryStrategy.REPHRASE, RecoveryStrategy.SIMPLIFY]
        )
        result = cascade.get_recovery(0, _STUCK_SIGNAL, "goal")
        assert result.should_continue is True
        result = cascade.get_recovery(1, _STUCK_SIGNAL, "goal")
        assert result.should_continue is True
        # Beyond last → ESCALATE
        result = cascade.get_recovery(2, _STUCK_SIGNAL, "goal")
        assert result.should_continue is False
