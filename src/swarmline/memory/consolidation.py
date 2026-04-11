"""Memory consolidation — extracts semantic facts from episodic memories.

Finds recurring patterns across episodes and stores them as facts.
Works without LLM by default (keyword extraction); can use LLM via optional generator.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from swarmline.memory.episodic_types import Episode


@runtime_checkable
class FactExtractor(Protocol):
    """Protocol for extracting facts from episode clusters."""

    async def extract(self, episodes: list[Episode]) -> list[str]: ...


class KeywordFactExtractor:
    """Simple fact extractor — finds common patterns without LLM.

    Groups episodes by shared keywords in summaries and key_decisions,
    then generates facts from frequent clusters.
    """

    def __init__(self, min_frequency: int = 2) -> None:
        self._min_freq = min_frequency

    async def extract(self, episodes: list[Episode]) -> list[str]:
        if not episodes:
            return []

        # Count keyword co-occurrences across episodes
        word_counts: Counter[str] = Counter()
        for ep in episodes:
            words: set[str] = set()
            for text in [ep.summary, *ep.key_decisions, *ep.tags]:
                words.update(w.lower() for w in text.split() if len(w) > 3)
            for w in words:
                word_counts[w] += 1

        # Find recurring themes (words appearing in >= min_freq episodes)
        themes = [w for w, c in word_counts.most_common(20) if c >= self._min_freq]
        if not themes:
            return []

        # Generate facts from theme clusters
        facts: list[str] = []
        # Group episodes by outcome
        outcomes = Counter(ep.outcome for ep in episodes)
        if outcomes.get("success", 0) >= self._min_freq:
            tools = Counter(t for ep in episodes for t in ep.tools_used if ep.outcome == "success")
            if tools:
                top_tool = tools.most_common(1)[0][0]
                facts.append(f"Tool '{top_tool}' is frequently used in successful tasks")

        # Tag-based patterns
        tag_counts = Counter(t for ep in episodes for t in ep.tags)
        for tag, count in tag_counts.most_common(5):
            if count >= self._min_freq:
                successes = sum(
                    1 for ep in episodes if tag in ep.tags and ep.outcome == "success"
                )
                if successes >= self._min_freq:
                    facts.append(
                        f"Tasks tagged '{tag}' succeed {successes}/{count} times"
                    )

        return facts


@dataclass
class ConsolidationResult:
    """Result of a consolidation run."""

    new_facts: tuple[str, ...]
    episodes_processed: int
    clusters_found: int


class ConsolidationPipeline:
    """Extracts semantic facts from episodic memories.

    1. Recall recent episodes
    2. Extract patterns via FactExtractor
    3. Deduplicate against existing facts
    4. Store new facts
    """

    def __init__(
        self,
        episodic: Any,
        fact_store: Any | None = None,
        extractor: Any | None = None,
    ) -> None:
        self._episodic = episodic
        self._fact_store = fact_store
        self._extractor = extractor or KeywordFactExtractor()
        self._stored_facts: list[str] = []

    async def consolidate(
        self,
        *,
        min_episodes: int = 3,
        max_episodes: int = 50,
    ) -> ConsolidationResult:
        """Run consolidation on recent episodes."""
        episodes = await self._episodic.recall_recent(n=max_episodes)

        if len(episodes) < min_episodes:
            return ConsolidationResult(
                new_facts=(), episodes_processed=len(episodes), clusters_found=0
            )

        # Extract facts from episodes
        raw_facts = await self._extractor.extract(episodes)

        # Deduplicate
        new_facts = [f for f in raw_facts if f not in self._stored_facts]
        self._stored_facts.extend(new_facts)

        # Store in fact store if provided
        if self._fact_store is not None and new_facts:
            for fact in new_facts:
                await self._fact_store.add_fact("system", fact)

        return ConsolidationResult(
            new_facts=tuple(new_facts),
            episodes_processed=len(episodes),
            clusters_found=len(raw_facts),
        )
