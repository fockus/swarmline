"""In-memory provider comparison — selects winner by mean score across dimensions."""

from __future__ import annotations

from swarmline.eval.coding_types import (
    ComparisonReport,
    GoldenTask,
    ProviderResult,
)


def _mean_score(result: ProviderResult) -> float:
    """Compute mean score across all outcome dimensions.

    Boolean dimensions contribute 1.0 (True) or 0.0 (False).
    diff_quality is already 0.0-1.0.
    5 dimensions total: tests_passed, lint_clean, mypy_clean, diff_quality, behavioral_pass.
    """
    o = result.outcome
    return (
        float(o.tests_passed)
        + float(o.lint_clean)
        + float(o.mypy_clean)
        + o.diff_quality
        + float(o.behavioral_pass)
    ) / 5.0


class InMemoryProviderComparison:
    """Compare provider results for a single task, select winner by mean score.

    Winner: provider with strictly highest mean score.
    Tie (two or more providers share the top score): winner_id = None.
    Empty results: winner_id = None.
    """

    def compare(
        self,
        task: GoldenTask,
        results: tuple[ProviderResult, ...],
    ) -> ComparisonReport:
        if not results:
            return ComparisonReport(task=task, results=results, winner_id=None)

        scored = [(r, _mean_score(r)) for r in results]
        scored.sort(key=lambda x: x[1], reverse=True)

        top_score = scored[0][1]
        top_providers = [r for r, s in scored if abs(s - top_score) < 1e-9]

        winner_id: str | None = None
        if len(top_providers) == 1:
            winner_id = top_providers[0].provider.provider_id

        return ComparisonReport(task=task, results=results, winner_id=winner_id)
