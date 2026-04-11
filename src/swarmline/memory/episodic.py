"""In-memory episodic memory — word overlap search (development/testing)."""

from __future__ import annotations

from swarmline.memory.episodic_types import Episode


class InMemoryEpisodicMemory:
    """Episodic memory backed by a Python list. Word-overlap search."""

    def __init__(self) -> None:
        self._episodes: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self._episodes.append(episode)

    async def recall(self, query: str, *, top_k: int = 5) -> list[Episode]:
        query_words = set(query.lower().split())
        scored = []
        for ep in self._episodes:
            text = f"{ep.summary} {' '.join(ep.tags)} {' '.join(ep.key_decisions)}"
            ep_words = set(text.lower().split())
            overlap = len(query_words & ep_words)
            if overlap > 0:
                scored.append((overlap, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:top_k]]

    async def recall_recent(self, n: int = 10) -> list[Episode]:
        sorted_eps = sorted(self._episodes, key=lambda e: e.timestamp, reverse=True)
        return sorted_eps[:n]

    async def recall_by_tag(self, tag: str) -> list[Episode]:
        return [ep for ep in self._episodes if tag in ep.tags]

    async def count(self) -> int:
        return len(self._episodes)
