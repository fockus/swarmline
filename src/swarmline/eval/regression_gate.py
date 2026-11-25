"""In-memory regression gate — baseline comparison with append-only history."""

from __future__ import annotations

from swarmline.eval.coding_types import RegressionGateResult


class InMemoryRegressionGate:
    """Check current score against stored baseline with configurable threshold.

    Tracks all baseline updates in append-only history.
    Degradation: baseline - current > threshold.
    """

    def __init__(self) -> None:
        self._baseline: float = 0.0
        self._history: list[float] = []

    @property
    def baseline_history(self) -> tuple[float, ...]:
        """Append-only history of all baseline values."""
        return tuple(self._history)

    def check_regression(
        self,
        current_score: float,
        threshold: float,
    ) -> RegressionGateResult:
        diff = self._baseline - current_score
        passed = diff <= threshold
        regressions: tuple[str, ...] = ()
        if not passed:
            regressions = ("score_degraded",)
        return RegressionGateResult(
            passed=passed,
            current_score=current_score,
            baseline_score=self._baseline,
            threshold=threshold,
            regressions=regressions,
        )

    def update_baseline(self, score: float) -> None:
        self._baseline = score
        self._history.append(score)
