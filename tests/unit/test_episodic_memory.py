"""Unit: episodic memory contract tests — parametrized for InMemory + SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swarmline.memory.episodic_types import Episode, EpisodicMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def inmemory_store():
    from swarmline.memory.episodic import InMemoryEpisodicMemory

    return InMemoryEpisodicMemory()


@pytest.fixture
def sqlite_store(tmp_path):
    from swarmline.memory.episodic_sqlite import SqliteEpisodicMemory

    return SqliteEpisodicMemory(str(tmp_path / "episodes.db"))


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request, inmemory_store, sqlite_store):
    if request.param == "inmemory":
        return inmemory_store
    return sqlite_store


def _ep(
    id: str = "ep1",
    summary: str = "Agent helped with research",
    tags: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    outcome: str = "success",
    ts: datetime | None = None,
) -> Episode:
    return Episode(
        id=id,
        summary=summary,
        tags=tags,
        tools_used=tools,
        outcome=outcome,
        session_id=f"sess-{id}",
        timestamp=ts or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Contract tests (run on both backends)
# ---------------------------------------------------------------------------


class TestEpisodicContract:
    async def test_store_and_count(self, store) -> None:
        assert await store.count() == 0
        await store.store(_ep("e1"))
        assert await store.count() == 1

    async def test_store_multiple(self, store) -> None:
        await store.store(_ep("e1"))
        await store.store(_ep("e2"))
        await store.store(_ep("e3"))
        assert await store.count() == 3

    async def test_recall_by_query(self, store) -> None:
        await store.store(_ep("e1", summary="Helped with Python debugging"))
        await store.store(_ep("e2", summary="Created a marketing plan"))
        results = await store.recall("Python debugging")
        assert len(results) >= 1
        assert any("Python" in r.summary for r in results)

    async def test_recall_top_k(self, store) -> None:
        for i in range(10):
            await store.store(_ep(f"e{i}", summary=f"Task {i} about coding"))
        results = await store.recall("coding", top_k=3)
        assert len(results) <= 3

    async def test_recall_recent(self, store) -> None:
        now = datetime.now(UTC)
        await store.store(_ep("old", summary="Old task", ts=now - timedelta(hours=10)))
        await store.store(_ep("mid", summary="Mid task", ts=now - timedelta(hours=5)))
        await store.store(_ep("new", summary="New task", ts=now))
        results = await store.recall_recent(n=2)
        assert len(results) == 2
        assert results[0].id == "new"
        assert results[1].id == "mid"

    async def test_recall_by_tag(self, store) -> None:
        await store.store(_ep("e1", tags=("research", "python")))
        await store.store(_ep("e2", tags=("marketing",)))
        await store.store(_ep("e3", tags=("research", "data")))
        results = await store.recall_by_tag("research")
        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"e1", "e3"}

    async def test_recall_by_tag_empty(self, store) -> None:
        await store.store(_ep("e1", tags=("a",)))
        results = await store.recall_by_tag("nonexistent")
        assert results == []

    async def test_recall_empty_store(self, store) -> None:
        results = await store.recall("anything")
        assert results == []

    async def test_recall_recent_empty(self, store) -> None:
        results = await store.recall_recent()
        assert results == []

    async def test_episode_fields_preserved(self, store) -> None:
        ep = Episode(
            id="rich",
            summary="Complex task",
            key_decisions=("used API A", "chose format JSON"),
            tools_used=("web_search", "code_sandbox"),
            outcome="success",
            session_id="sess-42",
            timestamp=datetime(2026, 1, 15, 10, 30),
            tags=("complex", "api"),
            metadata={"tokens": 1500},
        )
        await store.store(ep)
        results = await store.recall("Complex task")
        assert len(results) >= 1
        r = results[0]
        assert r.id == "rich"
        assert r.key_decisions == ("used API A", "chose format JSON")
        assert r.tools_used == ("web_search", "code_sandbox")
        assert r.outcome == "success"
        assert r.tags == ("complex", "api")

    async def test_implements_protocol(self, store) -> None:
        assert isinstance(store, EpisodicMemory)

    async def test_episodic_concurrent_store_recall(self, store) -> None:
        """Concurrent store() and recall() must not raise threading errors."""
        import asyncio

        episodes = [
            _ep(f"conc-{i}", summary=f"Concurrent episode {i}") for i in range(20)
        ]

        # Store all concurrently
        await asyncio.gather(*[store.store(ep) for ep in episodes])

        # Recall concurrently while storing more
        extra_stores = [
            store.store(_ep(f"extra-{i}", summary=f"Extra episode {i}"))
            for i in range(10)
        ]
        recalls = [store.recall("episode") for _ in range(10)]
        counts = [store.count() for _ in range(5)]
        recents = [store.recall_recent(5) for _ in range(5)]

        results = await asyncio.gather(
            *extra_stores,
            *recalls,
            *counts,
            *recents,
            return_exceptions=True,
        )

        # No exceptions should have been raised
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert exceptions == [], f"Concurrent ops raised: {exceptions}"

        # All episodes should be stored
        final_count = await store.count()
        assert final_count == 30  # 20 initial + 10 extra


# ---------------------------------------------------------------------------
# SQLite-specific: FTS5 dedup on INSERT OR REPLACE
# ---------------------------------------------------------------------------


class TestSqliteFtsDedup:
    """Verify FTS5 triggers correctly remove stale entries on replace."""

    async def test_store_replace_same_id_deduplicates_fts(self, sqlite_store) -> None:
        """INSERT OR REPLACE must not leave stale FTS entries.

        Store episode, replace with same ID but different summary,
        recall must return exactly one result with the new summary.
        """
        ep_v1 = _ep("dup-1", summary="Old summary about apples")
        await sqlite_store.store(ep_v1)

        ep_v2 = _ep("dup-1", summary="New summary about oranges")
        await sqlite_store.store(ep_v2)

        assert await sqlite_store.count() == 1

        results_old = await sqlite_store.recall("apples")
        results_new = await sqlite_store.recall("oranges")
        assert len(results_new) == 1
        assert results_new[0].summary == "New summary about oranges"
        assert len(results_old) == 0, "Stale FTS entry for old summary should be gone"
