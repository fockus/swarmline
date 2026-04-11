"""Builtin evaluation scorers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from swarmline.eval.types import EvalCase, ScorerResult


# ---------------------------------------------------------------------------
# ExactMatchScorer
# ---------------------------------------------------------------------------


@dataclass
class ExactMatchScorer:
    """Score 1.0 if output exactly matches expected, 0.0 otherwise."""

    case_sensitive: bool = True

    @property
    def name(self) -> str:
        return "exact_match"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        if case.expected is None:
            return ScorerResult(score=0.0, reason="no expected value")
        expected = case.expected
        actual = output
        if not self.case_sensitive:
            expected = expected.lower()
            actual = actual.lower()
        if actual == expected:
            return ScorerResult(score=1.0, reason="exact match")
        return ScorerResult(
            score=0.0,
            reason="mismatch",
            details={"expected": case.expected, "actual": output[:200]},
        )


# ---------------------------------------------------------------------------
# ContainsScorer
# ---------------------------------------------------------------------------


@dataclass
class ContainsScorer:
    """Score 1.0 if expected string is found within output."""

    case_sensitive: bool = True

    @property
    def name(self) -> str:
        return "contains"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        if case.expected is None:
            return ScorerResult(score=0.0, reason="no expected value")
        expected = case.expected
        actual = output
        if not self.case_sensitive:
            expected = expected.lower()
            actual = actual.lower()
        if expected in actual:
            return ScorerResult(score=1.0, reason="found in output")
        return ScorerResult(score=0.0, reason="not found in output")


# ---------------------------------------------------------------------------
# RegexScorer
# ---------------------------------------------------------------------------


@dataclass
class RegexScorer:
    """Score 1.0 if output matches a regex pattern."""

    pattern: str | None = None

    @property
    def name(self) -> str:
        return "regex"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        pat = self.pattern or case.expected
        if pat is None:
            return ScorerResult(score=0.0, reason="no pattern")
        if re.search(pat, output):
            return ScorerResult(score=1.0, reason="pattern matched")
        return ScorerResult(score=0.0, reason="pattern not matched")


# ---------------------------------------------------------------------------
# LatencyScorer
# ---------------------------------------------------------------------------


@dataclass
class LatencyScorer:
    """Score based on response latency. 1.0 if under max_ms, degrades linearly."""

    max_ms: float = 5000.0

    @property
    def name(self) -> str:
        return "latency"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        latency = case.context.get("latency_ms", 0.0)
        if not isinstance(latency, (int, float)):
            return ScorerResult(score=1.0, reason="no latency data")
        if latency <= self.max_ms:
            return ScorerResult(
                score=1.0,
                reason=f"{latency:.0f}ms <= {self.max_ms:.0f}ms",
                details={"latency_ms": latency},
            )
        # Linear degradation: 2x over = 0.0
        ratio = latency / self.max_ms
        score = max(0.0, 1.0 - (ratio - 1.0))
        return ScorerResult(
            score=score,
            reason=f"{latency:.0f}ms > {self.max_ms:.0f}ms",
            details={"latency_ms": latency, "ratio": ratio},
        )


# ---------------------------------------------------------------------------
# CostScorer
# ---------------------------------------------------------------------------


@dataclass
class CostScorer:
    """Score based on cost. 1.0 if under budget, degrades linearly."""

    max_cost_usd: float = 1.0

    @property
    def name(self) -> str:
        return "cost"

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        cost = case.context.get("cost_usd")
        if cost is None:
            return ScorerResult(score=1.0, reason="no cost data")
        if not isinstance(cost, (int, float)):
            return ScorerResult(score=1.0, reason="invalid cost data")
        if cost <= self.max_cost_usd:
            return ScorerResult(
                score=1.0,
                reason=f"${cost:.4f} <= ${self.max_cost_usd:.4f}",
                details={"cost_usd": cost},
            )
        ratio = cost / self.max_cost_usd
        score = max(0.0, 1.0 - (ratio - 1.0))
        return ScorerResult(
            score=score,
            reason=f"${cost:.4f} > ${self.max_cost_usd:.4f}",
            details={"cost_usd": cost, "ratio": ratio},
        )
