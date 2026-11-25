"""Tests for InMemoryRegressionGate.

TDD: written BEFORE implementation.
Covers: baseline comparison, threshold, degradation tracking, append-only history.
"""

from __future__ import annotations

import pytest
from swarmline.eval.coding_protocols import RegressionGatePort
from swarmline.eval.coding_types import RegressionGateResult
from swarmline.eval.regression_gate import InMemoryRegressionGate


class TestInMemoryRegressionGateProtocol:
    def test_implements_protocol(self) -> None:
        gate = InMemoryRegressionGate()
        assert isinstance(gate, RegressionGatePort)


class TestCheckRegressionBaseline:
    def test_passes_when_score_above_baseline(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.8)
        result = gate.check_regression(current_score=0.85, threshold=0.1)
        assert isinstance(result, RegressionGateResult)
        assert result.passed is True
        assert result.regressions == ()

    def test_passes_when_score_equal_to_baseline(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.8)
        result = gate.check_regression(current_score=0.8, threshold=0.1)
        assert result.passed is True

    def test_passes_when_degradation_within_threshold(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.8)
        result = gate.check_regression(current_score=0.75, threshold=0.1)
        assert result.passed is True  # diff=0.05 <= 0.1

    def test_fails_when_degradation_exceeds_threshold(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.9)
        result = gate.check_regression(current_score=0.5, threshold=0.1)
        assert result.passed is False

    def test_fails_at_exact_threshold_boundary(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(1.0)
        # diff = 1.0 - 0.75 = 0.25, threshold = 0.25 → passes (<=)
        result = gate.check_regression(current_score=0.75, threshold=0.25)
        assert result.passed is True

    def test_default_baseline_is_zero(self) -> None:
        gate = InMemoryRegressionGate()
        result = gate.check_regression(current_score=0.5, threshold=0.1)
        assert result.passed is True  # baseline=0, current=0.5, no degradation
        assert result.baseline_score == 0.0


class TestCheckRegressionScoresReported:
    def test_reports_current_and_baseline_scores(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.85)
        result = gate.check_regression(0.7, 0.05)
        assert result.current_score == 0.7
        assert result.baseline_score == 0.85
        assert result.threshold == 0.05


class TestDegradationTracking:
    def test_regression_lists_score_degraded(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.9)
        result = gate.check_regression(current_score=0.5, threshold=0.1)
        assert result.passed is False
        assert len(result.regressions) > 0
        assert "score_degraded" in result.regressions

    def test_no_regressions_when_passing(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.8)
        result = gate.check_regression(current_score=0.85, threshold=0.1)
        assert result.regressions == ()


class TestUpdateBaseline:
    def test_update_baseline_changes_reference(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.5)
        r1 = gate.check_regression(0.45, 0.1)
        assert r1.passed is True  # diff=0.05 <= 0.1

        gate.update_baseline(0.9)
        r2 = gate.check_regression(0.45, 0.1)
        assert r2.passed is False  # diff=0.45 > 0.1

    def test_multiple_baseline_updates(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.5)
        gate.update_baseline(0.7)
        gate.update_baseline(0.9)
        result = gate.check_regression(0.85, 0.1)
        assert result.baseline_score == 0.9


class TestAppendOnlyHistory:
    def test_history_starts_empty(self) -> None:
        gate = InMemoryRegressionGate()
        assert gate.baseline_history == ()

    def test_history_records_each_update(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.5)
        gate.update_baseline(0.7)
        gate.update_baseline(0.9)
        history = gate.baseline_history
        assert len(history) == 3
        assert history[0] == 0.5
        assert history[1] == 0.7
        assert history[2] == 0.9

    def test_history_is_append_only(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.5)
        gate.update_baseline(0.3)  # intentionally lower
        history = gate.baseline_history
        assert len(history) == 2
        assert history == (0.5, 0.3)

    def test_history_is_tuple_immutable(self) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(0.5)
        h = gate.baseline_history
        assert isinstance(h, tuple)


class TestThresholdEdgeCases:
    @pytest.mark.parametrize(
        ("baseline", "current", "threshold", "expected_passed"),
        [
            (0.0, 0.0, 0.0, True),  # zero everything
            (1.0, 1.0, 0.0, True),  # perfect score, zero tolerance
            (1.0, 0.0, 0.5, False),  # big drop, moderate threshold
            (0.5, 0.5, 0.0, True),  # same score, zero threshold
            (0.75, 0.5, 0.25, True),  # diff exactly at threshold
        ],
    )
    def test_parametrized_threshold_cases(
        self,
        baseline: float,
        current: float,
        threshold: float,
        expected_passed: bool,
    ) -> None:
        gate = InMemoryRegressionGate()
        gate.update_baseline(baseline)
        result = gate.check_regression(current, threshold)
        assert result.passed is expected_passed
