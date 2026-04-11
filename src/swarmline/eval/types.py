"""Evaluation framework types — frozen dataclasses and protocols."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class EvalCase:
    """A single evaluation test case."""

    id: str
    input: str
    expected: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScorerResult:
    """Result from a single scorer on a single case."""

    score: float  # 0.0–1.0
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalResult:
    """Result for a single case across all scorers."""

    case: EvalCase
    output: str
    scores: dict[str, ScorerResult] = field(default_factory=dict)
    error: str | None = None
    latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        """True if no error and all scores >= threshold (default 0.5)."""
        if self.error:
            return False
        return all(s.score >= 0.5 for s in self.scores.values())

    @property
    def mean_score(self) -> float:
        if not self.scores:
            return 0.0
        return statistics.mean(s.score for s in self.scores.values())


@dataclass(frozen=True)
class EvalReport:
    """Aggregated evaluation report across all cases."""

    results: tuple[EvalResult, ...]
    pass_threshold: float = 0.5

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return statistics.mean(r.mean_score for r in self.results)

    @property
    def scores_by_scorer(self) -> dict[str, list[float]]:
        """Group scores by scorer name."""
        result: dict[str, list[float]] = {}
        for r in self.results:
            for name, s in r.scores.items():
                result.setdefault(name, []).append(s.score)
        return result

    def scorer_stats(self, scorer_name: str) -> dict[str, float]:
        """Return mean, min, max, p50, p95 for a specific scorer."""
        scores = self.scores_by_scorer.get(scorer_name, [])
        if not scores:
            return {}
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        return {
            "mean": statistics.mean(sorted_scores),
            "min": min(sorted_scores),
            "max": max(sorted_scores),
            "p50": sorted_scores[n // 2],
            "p95": sorted_scores[int(n * 0.95)] if n >= 2 else sorted_scores[-1],
        }


@runtime_checkable
class Scorer(Protocol):
    """Protocol for evaluation scorers."""

    @property
    def name(self) -> str: ...

    async def score(self, case: EvalCase, output: str) -> ScorerResult: ...
