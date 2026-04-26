"""Unit: memory consolidation pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swarmline.memory.consolidation import (
    ConsolidationPipeline,
    ConsolidationResult,
    KeywordFactExtractor,
)
from swarmline.memory.episodic import InMemoryEpisodicMemory
from swarmline.memory.episodic_types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ep(
    id: str,
    summary: str = "task",
    tools: tuple[str, ...] = (),
    outcome: str = "success",
    tags: tuple[str, ...] = (),
    hours_ago: int = 0,
) -> Episode:
    return Episode(
        id=id,
        summary=summary,
        tools_used=tools,
        outcome=outcome,
        tags=tags,
        session_id=f"s-{id}",
        timestamp=datetime.now(UTC) - timedelta(hours=hours_ago),
    )


# ---------------------------------------------------------------------------
# KeywordFactExtractor
# ---------------------------------------------------------------------------


class TestKeywordFactExtractor:
    async def test_extracts_tool_pattern(self) -> None:
        extractor = KeywordFactExtractor(min_frequency=2)
        episodes = [
            _ep("e1", "research task", tools=("web_search",), outcome="success"),
            _ep("e2", "another research", tools=("web_search",), outcome="success"),
            _ep("e3", "coding task", tools=("sandbox",), outcome="success"),
        ]
        facts = await extractor.extract(episodes)
        assert any("web_search" in f for f in facts)

    async def test_extracts_tag_pattern(self) -> None:
        extractor = KeywordFactExtractor(min_frequency=2)
        episodes = [
            _ep("e1", "task 1", tags=("research",), outcome="success"),
            _ep("e2", "task 2", tags=("research",), outcome="success"),
            _ep("e3", "task 3", tags=("coding",), outcome="failure"),
        ]
        facts = await extractor.extract(episodes)
        assert any("research" in f for f in facts)

    async def test_empty_episodes(self) -> None:
        extractor = KeywordFactExtractor()
        facts = await extractor.extract([])
        assert facts == []

    async def test_single_episode_no_patterns(self) -> None:
        extractor = KeywordFactExtractor(min_frequency=2)
        facts = await extractor.extract([_ep("e1")])
        assert facts == []


# ---------------------------------------------------------------------------
# ConsolidationPipeline
# ---------------------------------------------------------------------------


class TestConsolidationPipeline:
    async def test_consolidate_below_min_episodes(self) -> None:
        episodic = InMemoryEpisodicMemory()
        await episodic.store(_ep("e1"))
        pipeline = ConsolidationPipeline(episodic=episodic)
        result = await pipeline.consolidate(min_episodes=5)
        assert result.episodes_processed == 1
        assert result.new_facts == ()

    async def test_consolidate_extracts_facts(self) -> None:
        episodic = InMemoryEpisodicMemory()
        for i in range(5):
            await episodic.store(
                _ep(
                    f"e{i}",
                    summary=f"research task {i}",
                    tools=("web_search",),
                    outcome="success",
                    tags=("research",),
                    hours_ago=i,
                )
            )
        pipeline = ConsolidationPipeline(episodic=episodic)
        result = await pipeline.consolidate(min_episodes=3)
        assert result.episodes_processed == 5
        assert len(result.new_facts) >= 1

    async def test_deduplication(self) -> None:
        episodic = InMemoryEpisodicMemory()
        for i in range(5):
            await episodic.store(
                _ep(
                    f"e{i}",
                    tools=("web_search",),
                    outcome="success",
                    tags=("research",),
                )
            )
        pipeline = ConsolidationPipeline(episodic=episodic)

        # First consolidation
        await pipeline.consolidate(min_episodes=2)
        # Second consolidation — should NOT produce duplicates
        r2 = await pipeline.consolidate(min_episodes=2)
        assert len(r2.new_facts) == 0

    async def test_consolidation_result_type(self) -> None:
        episodic = InMemoryEpisodicMemory()
        pipeline = ConsolidationPipeline(episodic=episodic)
        result = await pipeline.consolidate()
        assert isinstance(result, ConsolidationResult)

    async def test_custom_extractor(self) -> None:
        class FixedExtractor:
            async def extract(self, episodes: list) -> list[str]:
                return ["fixed fact 1", "fixed fact 2"]

        episodic = InMemoryEpisodicMemory()
        for i in range(5):
            await episodic.store(_ep(f"e{i}"))
        pipeline = ConsolidationPipeline(episodic=episodic, extractor=FixedExtractor())
        result = await pipeline.consolidate(min_episodes=2)
        assert "fixed fact 1" in result.new_facts
        assert "fixed fact 2" in result.new_facts
