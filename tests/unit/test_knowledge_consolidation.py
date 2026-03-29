"""Tests for KnowledgeConsolidator -- episodic memory to knowledge entries."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cognitia.memory_bank.knowledge_consolidation import KnowledgeConsolidator
from cognitia.memory_bank.knowledge_types import KnowledgeEntry


@dataclass(frozen=True)
class FakeEpisode:
    """Minimal episode-like object for testing."""

    summary: str = ""
    key_decisions: tuple[str, ...] = ()
    tools_used: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _make_episodes(tag: str, count: int) -> list[FakeEpisode]:
    return [
        FakeEpisode(
            summary=f"Episode {i} about {tag}",
            key_decisions=(f"decision-{i}",),
            tools_used=(f"tool-{i}",),
            tags=(tag,),
        )
        for i in range(count)
    ]


class TestKnowledgeConsolidator:
    def test_consolidate_empty_returns_empty(self) -> None:
        c = KnowledgeConsolidator()
        result = c.consolidate([])
        assert result == []

    def test_consolidate_below_min_returns_empty(self) -> None:
        episodes = _make_episodes("python", 2)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)
        assert result == []

    def test_consolidate_groups_by_tag(self) -> None:
        episodes = _make_episodes("python", 4) + _make_episodes("rare", 1)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)

        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, KnowledgeEntry)
        assert "python" in entry.path
        assert entry.meta.kind == "note"
        assert "python" in entry.meta.tags

    def test_consolidate_includes_decisions(self) -> None:
        episodes = _make_episodes("testing", 3)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)

        assert len(result) == 1
        assert "decision-0" in result[0].content
        assert "Key Decisions" in result[0].content

    def test_consolidate_includes_tools(self) -> None:
        episodes = _make_episodes("deploy", 3)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)

        assert len(result) == 1
        assert "Tools Used" in result[0].content

    def test_consolidate_creates_valid_meta(self) -> None:
        episodes = _make_episodes("arch", 5)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)

        assert len(result) == 1
        meta = result[0].meta
        assert meta.kind == "note"
        assert "arch" in meta.tags
        assert meta.importance == "medium"
        assert meta.created != ""
        assert meta.updated != ""

    def test_consolidate_size_bytes_matches_content(self) -> None:
        episodes = _make_episodes("metrics", 3)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=3)

        entry = result[0]
        assert entry.size_bytes == len(entry.content.encode("utf-8"))

    @pytest.mark.parametrize("min_ep", [1, 2, 5])
    def test_consolidate_respects_min_episodes(self, min_ep: int) -> None:
        episodes = _make_episodes("tag", 3)
        c = KnowledgeConsolidator()
        result = c.consolidate(episodes, min_episodes=min_ep)

        if min_ep <= 3:
            assert len(result) == 1
        else:
            assert len(result) == 0
