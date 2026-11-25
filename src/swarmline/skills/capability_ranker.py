"""Multi-factor weighted ranker for CapabilityDoc candidates.

REQ-OSS-051: no product coupling; all scoring factors are derived from
CapabilityDoc fields plus caller-supplied context (semantic scores, runtime).
REQ-OSS-050: this ranker is opt-in; the default ProactiveSkillInjector path
remains byte-identical until a CapabilityRanker is explicitly passed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from swarmline.skills.capability import CapabilityDoc


@dataclass(slots=True, frozen=True)
class RankWeights:
    """Configurable weights for the five-factor ranker.

    All weights must sum to 1.0 (validated by ``validate()``).
    Default weights mirror the taskloom CapabilityRanker formula.

    Factors
    -------
    semantic    BM25 / embedding score from the retriever
    runtime     Whether the active runtime is in capability.runtime_allow
    latency     "fast" → 1.0, "normal" → 0.5, "slow" → 0.0
    cost        "cheap" → 1.0, "normal" → 0.5, "expensive" → 0.0
    availability capability.enabled flag
    """

    semantic: float = 0.45
    runtime: float = 0.15
    latency: float = 0.10
    cost: float = 0.10
    availability: float = 0.20

    def validate(self) -> None:
        """Raise ValueError if weights are non-finite or do not sum to 1.0.

        NaN weights are explicitly rejected: ``abs(nan - 1.0) > 1e-6`` evaluates
        to False (all NaN comparisons return False), so the finiteness guard must
        precede the sum check.
        """
        total = (
            self.semantic + self.runtime + self.latency + self.cost + self.availability
        )
        if not math.isfinite(total) or abs(total - 1.0) > 1e-6:
            raise ValueError(f"RankWeights must sum to 1.0 (finite), got {total}")


@dataclass(slots=True, frozen=True)
class RankedCapability:
    """A CapabilityDoc paired with its multi-factor score."""

    capability: CapabilityDoc
    score: float
    factor_scores: dict[str, float] = field(default_factory=dict)


def _latency_score(hint: str) -> float:
    return {"fast": 1.0, "normal": 0.5, "slow": 0.0}.get(hint, 0.5)


def _cost_score(hint: str) -> float:
    return {"cheap": 1.0, "normal": 0.5, "expensive": 0.0}.get(hint, 0.5)


class CapabilityRanker:
    """Weighted multi-factor ranker for CapabilityDoc lists.

    Usage::

        ranker = CapabilityRanker()
        ranked = ranker.rank(
            candidates,
            semantic_scores={"skill:web-search": 0.85, ...},
            available_runtime="thin",
        )
        top = ranked[0].capability

    The ranker is STATELESS across calls — results depend only on the
    inputs, not on any accumulated state.
    """

    def __init__(self, weights: RankWeights | None = None) -> None:
        resolved = weights or RankWeights()
        resolved.validate()  # reject non-normalised weights at the boundary
        self._weights = resolved

    def rank(
        self,
        candidates: list[CapabilityDoc],
        *,
        semantic_scores: dict[str, float] | None = None,
        available_runtime: str = "",
        available_capabilities: set[str] | None = None,
    ) -> list[RankedCapability]:
        """Score all candidates and return them sorted descending by total score.

        Args:
            candidates: docs to rank.
            semantic_scores: maps capability_id → float in [0, 1].
                Capabilities absent from the map receive a semantic score of 0.0.
            available_runtime: active runtime name used for the runtime factor.
                An empty string disables runtime scoring (all docs get 0.0).
            available_capabilities: reserved for subclass extension;
                not used in the base implementation.
        """
        if not candidates:
            return []

        w = self._weights
        scores_map = semantic_scores or {}
        ranked: list[RankedCapability] = []

        for cap in candidates:
            sem = max(0.0, min(1.0, scores_map.get(cap.capability_id, 0.0)))
            rt = (
                1.0
                if (available_runtime and available_runtime in cap.runtime_allow)
                else 0.0
            )
            lat = _latency_score(cap.latency_hint)
            cost = _cost_score(cap.cost_hint)
            avail = 1.0 if cap.enabled else 0.0

            total = (
                w.semantic * sem
                + w.runtime * rt
                + w.latency * lat
                + w.cost * cost
                + w.availability * avail
            )

            ranked.append(
                RankedCapability(
                    capability=cap,
                    score=total,
                    factor_scores={
                        "semantic": sem,
                        "runtime": rt,
                        "latency": lat,
                        "cost": cost,
                        "availability": avail,
                    },
                )
            )

        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked
