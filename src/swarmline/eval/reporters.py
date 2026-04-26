"""Evaluation report formatters — console, JSON, CSV."""

from __future__ import annotations

import json
from dataclasses import dataclass

from swarmline.eval.types import EvalReport


@dataclass
class ConsoleReporter:
    """Format evaluation report as human-readable text."""

    def format(self, report: EvalReport) -> str:
        lines: list[str] = []
        lines.append(
            f"Eval Report: {report.passed}/{report.total} passed "
            f"({report.pass_rate:.0%}), mean score: {report.mean_score:.2f}"
        )
        lines.append("-" * 60)

        for result in report.results:
            status = "PASS" if result.passed else "FAIL"
            scores_str = ", ".join(
                f"{name}={sr.score:.2f}" for name, sr in result.scores.items()
            )
            line = f"  [{status}] {result.case.id}: {scores_str}"
            if result.error:
                line += f" ERROR: {result.error[:80]}"
            lines.append(line)

        if report.total > 0:
            lines.append("-" * 60)
            for scorer_name, scores in report.scores_by_scorer.items():
                stats = report.scorer_stats(scorer_name)
                lines.append(
                    f"  {scorer_name}: mean={stats.get('mean', 0):.2f} "
                    f"min={stats.get('min', 0):.2f} max={stats.get('max', 0):.2f}"
                )

        return "\n".join(lines)


@dataclass
class JsonReporter:
    """Format evaluation report as JSON."""

    indent: int = 2

    def format(self, report: EvalReport) -> str:
        data = {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "mean_score": report.mean_score,
            "results": [
                {
                    "case_id": r.case.id,
                    "input": r.case.input,
                    "output": r.output[:500],
                    "error": r.error,
                    "latency_ms": round(r.latency_ms, 1),
                    "passed": r.passed,
                    "mean_score": round(r.mean_score, 3),
                    "scores": {
                        name: {"score": round(sr.score, 3), "reason": sr.reason}
                        for name, sr in r.scores.items()
                    },
                }
                for r in report.results
            ],
            "scorer_stats": {
                name: report.scorer_stats(name) for name in report.scores_by_scorer
            },
        }
        return json.dumps(data, indent=self.indent, ensure_ascii=False)
