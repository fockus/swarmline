"""Eval history — save/load evaluation results to JSON."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from swarmline.eval.types import EvalCase, EvalReport, EvalResult, ScorerResult


class EvalHistory:
    """Persist and load EvalReport to/from JSON files."""

    @staticmethod
    def save(
        report: EvalReport,
        path: Path | str,
        *,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save an EvalReport to a JSON file."""
        path = Path(path)
        data: dict[str, Any] = {
            "run_id": run_id or f"run-{int(time.time())}",
            "timestamp": time.time(),
            "metadata": metadata or {},
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "mean_score": report.mean_score,
            "results": [
                {
                    "case_id": r.case.id,
                    "input": r.case.input,
                    "expected": r.case.expected,
                    "context": r.case.context,
                    "tags": list(r.case.tags),
                    "output": r.output,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                    "scores": {
                        name: {
                            "score": sr.score,
                            "reason": sr.reason,
                            "details": sr.details,
                        }
                        for name, sr in r.scores.items()
                    },
                }
                for r in report.results
            ],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def load(path: Path | str) -> EvalReport:
        """Load an EvalReport from a JSON file."""
        path = Path(path)
        data = json.loads(path.read_text())

        results: list[EvalResult] = []
        for r in data["results"]:
            case = EvalCase(
                id=r["case_id"],
                input=r["input"],
                expected=r.get("expected"),
                context=r.get("context", {}),
                tags=tuple(r.get("tags", ())),
            )
            scores = {
                name: ScorerResult(
                    score=s["score"],
                    reason=s.get("reason", ""),
                    details=s.get("details", {}),
                )
                for name, s in r.get("scores", {}).items()
            }
            results.append(EvalResult(
                case=case,
                output=r.get("output", ""),
                error=r.get("error"),
                latency_ms=r.get("latency_ms", 0.0),
                scores=scores,
            ))

        return EvalReport(results=tuple(results))
