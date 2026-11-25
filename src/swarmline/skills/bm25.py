"""BM25 retriever for skill discovery — pure Python, no external deps."""

from __future__ import annotations

import math
import re
from collections import Counter

from swarmline.skills.protocols import ScoredSkill
from swarmline.skills.types import SkillSpec

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric."""
    return [tok for tok in _SPLIT_RE.split(text.lower()) if tok]


def _skill_tokens(skill: SkillSpec) -> list[str]:
    """Build token bag from title + description + keywords + intents."""
    parts: list[str] = [skill.title, skill.description]
    parts.extend(skill.keywords)
    parts.extend(skill.intents)
    return _tokenize(" ".join(parts))


class BM25Retriever:
    """BM25 retriever implementing SkillRetriever Protocol.

    Pure Python implementation of Okapi BM25.
    Builds an ephemeral index per `retrieve` call (candidate list is small).
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        min_score: float = 0.1,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.min_score = min_score

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 8
    ) -> list[ScoredSkill]:
        """Score *candidates* against *query* using BM25, return top-k above threshold."""
        query_tokens = _tokenize(query)
        if not query_tokens or not candidates:
            return []

        # Build document token bags
        doc_tokens = [_skill_tokens(c) for c in candidates]
        doc_lengths = [len(d) for d in doc_tokens]
        avg_dl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0
        n = len(candidates)

        # Document frequency for each query term
        df: dict[str, int] = {}
        for qt in query_tokens:
            if qt not in df:
                df[qt] = sum(1 for d in doc_tokens if qt in d)

        # IDF (with +0.5 smoothing to avoid negative values)
        idf: dict[str, float] = {}
        for term, freq in df.items():
            idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

        # BM25 score per document
        raw_scores: list[float] = []
        for i, tokens in enumerate(doc_tokens):
            tf_map = Counter(tokens)
            dl = doc_lengths[i]
            score = 0.0
            for qt in query_tokens:
                tf = tf_map.get(qt, 0)
                if tf == 0:
                    continue
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * dl / avg_dl)
                score += idf.get(qt, 0.0) * numerator / denominator
            raw_scores.append(score)

        # Normalize to [0, 1]
        max_score = max(raw_scores) if raw_scores else 1.0
        if max_score <= 0.0:
            return []
        normalized = [s / max_score for s in raw_scores]

        # Filter, sort, truncate
        scored: list[ScoredSkill] = []
        for i, norm_score in enumerate(normalized):
            if norm_score >= self.min_score:
                scored.append(
                    ScoredSkill(skill=candidates[i], score=norm_score, source="bm25")
                )
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]
