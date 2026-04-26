"""Eval comparison — diff between two EvalReports."""

from __future__ import annotations

from dataclasses import dataclass, field

from swarmline.eval.types import EvalReport, EvalResult


@dataclass(frozen=True)
class CaseComparison:
    """Comparison result for a single eval case."""

    case_id: str
    status: str  # "improved", "regressed", "unchanged", "new", "removed"
    base_mean: float = 0.0
    target_mean: float = 0.0
    score_deltas: dict[str, float] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        return self.target_mean - self.base_mean


@dataclass(frozen=True)
class ComparisonReport:
    """Aggregated comparison between two eval runs."""

    cases: tuple[CaseComparison, ...]
    base_mean_score: float = 0.0
    target_mean_score: float = 0.0
    base_pass_rate: float = 0.0
    target_pass_rate: float = 0.0

    @property
    def mean_score_delta(self) -> float:
        return self.target_mean_score - self.base_mean_score

    @property
    def pass_rate_delta(self) -> float:
        return self.target_pass_rate - self.base_pass_rate

    @property
    def improved(self) -> int:
        return sum(1 for c in self.cases if c.status == "improved")

    @property
    def regressed(self) -> int:
        return sum(1 for c in self.cases if c.status == "regressed")

    @property
    def unchanged(self) -> int:
        return sum(1 for c in self.cases if c.status == "unchanged")

    def format_summary(self) -> str:
        lines = [
            f"Comparison: {self.improved} improved, {self.regressed} regressed, "
            f"{self.unchanged} unchanged",
            f"Mean score: {self.base_mean_score:.2f} -> {self.target_mean_score:.2f} "
            f"({self.mean_score_delta:+.2f})",
            f"Pass rate:  {self.base_pass_rate:.0%} -> {self.target_pass_rate:.0%} "
            f"({self.pass_rate_delta:+.0%})",
            "-" * 50,
        ]
        for c in self.cases:
            symbol = {
                "improved": "+",
                "regressed": "-",
                "unchanged": "=",
                "new": "N",
                "removed": "X",
            }[c.status]
            lines.append(
                f"  [{symbol}] {c.case_id}: {c.base_mean:.2f} -> {c.target_mean:.2f}"
            )
        return "\n".join(lines)


class EvalComparator:
    """Compare two EvalReports and produce a diff."""

    THRESHOLD = 0.05  # score delta below this = unchanged

    @staticmethod
    def compare(
        base: EvalReport,
        target: EvalReport,
        threshold: float = 0.05,
    ) -> ComparisonReport:
        base_by_id: dict[str, EvalResult] = {r.case.id: r for r in base.results}
        target_by_id: dict[str, EvalResult] = {r.case.id: r for r in target.results}

        all_ids = list(
            dict.fromkeys(
                [r.case.id for r in base.results] + [r.case.id for r in target.results]
            )
        )

        comparisons: list[CaseComparison] = []
        for cid in all_ids:
            b = base_by_id.get(cid)
            t = target_by_id.get(cid)

            if b is None and t is not None:
                comparisons.append(
                    CaseComparison(
                        case_id=cid,
                        status="new",
                        target_mean=t.mean_score,
                    )
                )
            elif t is None and b is not None:
                comparisons.append(
                    CaseComparison(
                        case_id=cid,
                        status="removed",
                        base_mean=b.mean_score,
                    )
                )
            elif b is not None and t is not None:
                delta = t.mean_score - b.mean_score
                # Per-scorer deltas
                all_scorers = set(b.scores) | set(t.scores)
                score_deltas = {}
                for s in all_scorers:
                    bs = b.scores.get(s)
                    ts = t.scores.get(s)
                    if bs and ts:
                        score_deltas[s] = ts.score - bs.score

                if delta > threshold:
                    status = "improved"
                elif delta < -threshold:
                    status = "regressed"
                else:
                    status = "unchanged"

                comparisons.append(
                    CaseComparison(
                        case_id=cid,
                        status=status,
                        base_mean=b.mean_score,
                        target_mean=t.mean_score,
                        score_deltas=score_deltas,
                    )
                )

        return ComparisonReport(
            cases=tuple(comparisons),
            base_mean_score=base.mean_score,
            target_mean_score=target.mean_score,
            base_pass_rate=base.pass_rate,
            target_pass_rate=target.pass_rate,
        )
