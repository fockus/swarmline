"""Tests for knowledge bank protocols and InMemory implementations."""

from __future__ import annotations

import pytest

from swarmline.memory_bank.knowledge_types import (
    ChecklistItem,
    DocumentKind,
    DocumentMeta,
    KnowledgeEntry,
    KnowledgeIndex,
    QualityCriterion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_entry(
    path: str = "notes/test.md",
    kind: DocumentKind = "note",
    content: str = "Test content",
    tags: tuple[str, ...] = (),
    importance: str = "medium",
) -> KnowledgeEntry:
    return KnowledgeEntry(
        path=path,
        meta=DocumentMeta(kind=kind, tags=tags, importance=importance),
        content=content,
        size_bytes=len(content.encode()),
    )


# ---------------------------------------------------------------------------
# Protocol isinstance checks
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Verify InMemory classes satisfy runtime_checkable protocols."""

    def test_knowledge_store_isinstance(self) -> None:
        from swarmline.memory_bank.knowledge_inmemory import InMemoryKnowledgeStore
        from swarmline.memory_bank.knowledge_protocols import KnowledgeStore

        assert isinstance(InMemoryKnowledgeStore(), KnowledgeStore)

    def test_knowledge_searcher_isinstance(self) -> None:
        from swarmline.memory_bank.knowledge_inmemory import (
            InMemoryKnowledgeSearcher,
            InMemoryKnowledgeStore,
        )
        from swarmline.memory_bank.knowledge_protocols import KnowledgeSearcher

        store = InMemoryKnowledgeStore()
        assert isinstance(InMemoryKnowledgeSearcher(store), KnowledgeSearcher)

    def test_progress_log_isinstance(self) -> None:
        from swarmline.memory_bank.knowledge_inmemory import InMemoryProgressLog
        from swarmline.memory_bank.knowledge_protocols import ProgressLog

        assert isinstance(InMemoryProgressLog(), ProgressLog)

    def test_checklist_manager_isinstance(self) -> None:
        from swarmline.memory_bank.knowledge_inmemory import InMemoryChecklistManager
        from swarmline.memory_bank.knowledge_protocols import ChecklistManager

        assert isinstance(InMemoryChecklistManager(), ChecklistManager)

    def test_null_verifier_isinstance(self) -> None:
        from swarmline.memory_bank.knowledge_inmemory import NullVerifier
        from swarmline.memory_bank.knowledge_protocols import VerificationStrategy

        assert isinstance(NullVerifier(), VerificationStrategy)


# ---------------------------------------------------------------------------
# KnowledgeStore tests
# ---------------------------------------------------------------------------


class TestInMemoryKnowledgeStore:
    """Test InMemoryKnowledgeStore CRUD operations."""

    @pytest.fixture()
    def store(self):
        from swarmline.memory_bank.knowledge_inmemory import InMemoryKnowledgeStore

        return InMemoryKnowledgeStore()

    async def test_store_save_load_roundtrip(self, store) -> None:
        entry = _make_entry(path="notes/hello.md", content="Hello world")

        await store.save(entry)
        loaded = await store.load("notes/hello.md")

        assert loaded is not None
        assert loaded.path == "notes/hello.md"
        assert loaded.content == "Hello world"
        assert loaded.meta.kind == "note"

    async def test_store_load_missing_returns_none(self, store) -> None:
        result = await store.load("nonexistent.md")
        assert result is None

    async def test_store_delete(self, store) -> None:
        entry = _make_entry(path="notes/del.md")
        await store.save(entry)
        await store.delete("notes/del.md")

        assert await store.load("notes/del.md") is None

    async def test_store_delete_nonexistent_is_graceful(self, store) -> None:
        await store.delete("nonexistent.md")  # should not raise

    async def test_store_list_entries_by_kind(self, store) -> None:
        await store.save(_make_entry(path="notes/a.md", kind="note"))
        await store.save(_make_entry(path="plans/b.md", kind="plan"))
        await store.save(_make_entry(path="notes/c.md", kind="note"))

        notes = await store.list_entries(kind="note")
        assert len(notes) == 2
        assert all(e.kind == "note" for e in notes)

        all_entries = await store.list_entries()
        assert len(all_entries) == 3

    async def test_store_exists(self, store) -> None:
        entry = _make_entry(path="notes/exists.md")
        await store.save(entry)

        assert await store.exists("notes/exists.md") is True
        assert await store.exists("notes/nope.md") is False

    async def test_store_save_overwrites(self, store) -> None:
        await store.save(_make_entry(path="notes/x.md", content="v1"))
        await store.save(_make_entry(path="notes/x.md", content="v2"))

        loaded = await store.load("notes/x.md")
        assert loaded is not None
        assert loaded.content == "v2"


# ---------------------------------------------------------------------------
# KnowledgeSearcher tests
# ---------------------------------------------------------------------------


class TestInMemoryKnowledgeSearcher:
    """Test InMemoryKnowledgeSearcher search and index operations."""

    @pytest.fixture()
    def store_and_searcher(self):
        from swarmline.memory_bank.knowledge_inmemory import (
            InMemoryKnowledgeSearcher,
            InMemoryKnowledgeStore,
        )

        store = InMemoryKnowledgeStore()
        searcher = InMemoryKnowledgeSearcher(store)
        return store, searcher

    async def test_search_by_text(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md", content="Python async programming"))
        await store.save(_make_entry(path="b.md", content="Rust memory safety"))
        await store.save(_make_entry(path="c.md", content="Python web framework"))

        results = await searcher.search("Python")
        assert len(results) == 2
        paths = {r.path for r in results}
        assert "a.md" in paths
        assert "c.md" in paths

    async def test_search_no_results(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md", content="Hello world"))

        results = await searcher.search("nonexistent_xyz_term")
        assert results == []

    async def test_search_empty_query_returns_empty(self, store_and_searcher) -> None:
        _, searcher = store_and_searcher
        results = await searcher.search("")
        assert results == []

    async def test_search_by_tags(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md", tags=("python", "async")))
        await store.save(_make_entry(path="b.md", tags=("rust", "safety")))
        await store.save(_make_entry(path="c.md", tags=("python", "web")))

        results = await searcher.search_by_tags(["python"])
        assert len(results) == 2
        paths = {r.path for r in results}
        assert paths == {"a.md", "c.md"}

    async def test_search_by_tags_case_insensitive(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md", tags=("Python",)))

        results = await searcher.search_by_tags(["python"])
        assert len(results) == 1

    async def test_search_by_tags_no_match(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md", tags=("rust",)))

        results = await searcher.search_by_tags(["python"])
        assert results == []

    async def test_rebuild_index(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md"))
        await store.save(_make_entry(path="b.md"))

        index = await searcher.rebuild_index()
        assert isinstance(index, KnowledgeIndex)
        assert len(index.entries) == 2
        assert index.version == 1

    async def test_get_index_auto_builds(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        await store.save(_make_entry(path="a.md"))

        index = await searcher.get_index()
        assert len(index.entries) == 1

    async def test_search_respects_top_k(self, store_and_searcher) -> None:
        store, searcher = store_and_searcher
        for i in range(5):
            await store.save(_make_entry(path=f"{i}.md", content="common word"))

        results = await searcher.search("common", top_k=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# ProgressLog tests
# ---------------------------------------------------------------------------


class TestInMemoryProgressLog:
    """Test InMemoryProgressLog append-only operations."""

    @pytest.fixture()
    def log(self):
        from swarmline.memory_bank.knowledge_inmemory import InMemoryProgressLog

        return InMemoryProgressLog()

    async def test_progress_append_and_recent(self, log) -> None:
        await log.append("First entry")
        await log.append("Second entry")

        recent = await log.get_recent(n=1)
        assert len(recent) == 1
        assert "Second entry" in recent[0]

    async def test_progress_get_all(self, log) -> None:
        await log.append("Entry 1", timestamp=False)
        await log.append("Entry 2", timestamp=False)

        text = await log.get_all()
        assert "Entry 1" in text
        assert "Entry 2" in text

    async def test_progress_append_with_timestamp(self, log) -> None:
        await log.append("Timestamped")

        entries = await log.get_recent(n=1)
        assert entries[0].startswith("[")
        assert "Timestamped" in entries[0]

    async def test_progress_append_without_timestamp(self, log) -> None:
        await log.append("Raw entry", timestamp=False)

        entries = await log.get_recent(n=1)
        assert entries[0] == "Raw entry"

    async def test_progress_get_recent_limits(self, log) -> None:
        for i in range(30):
            await log.append(f"Entry {i}", timestamp=False)

        recent = await log.get_recent(n=5)
        assert len(recent) == 5
        assert recent[-1] == "Entry 29"


# ---------------------------------------------------------------------------
# ChecklistManager tests
# ---------------------------------------------------------------------------


class TestInMemoryChecklistManager:
    """Test InMemoryChecklistManager task tracking."""

    @pytest.fixture()
    def mgr(self):
        from swarmline.memory_bank.knowledge_inmemory import InMemoryChecklistManager

        return InMemoryChecklistManager()

    async def test_checklist_add_and_get(self, mgr) -> None:
        await mgr.add_item(ChecklistItem(text="Task A"))
        await mgr.add_item(ChecklistItem(text="Task B"))

        items = await mgr.get_items()
        assert len(items) == 2
        assert items[0].text == "Task A"

    async def test_checklist_toggle(self, mgr) -> None:
        await mgr.add_item(ChecklistItem(text="Toggle me"))

        found = await mgr.toggle_item("Toggle")
        assert found is True

        items = await mgr.get_items()
        assert items[0].done is True

        # Toggle back
        await mgr.toggle_item("Toggle")
        items = await mgr.get_items()
        assert items[0].done is False

    async def test_checklist_toggle_not_found(self, mgr) -> None:
        found = await mgr.toggle_item("nonexistent")
        assert found is False

    async def test_checklist_filter_done(self, mgr) -> None:
        await mgr.add_item(ChecklistItem(text="Done task", done=True))
        await mgr.add_item(ChecklistItem(text="Pending task", done=False))

        done = await mgr.get_items(done=True)
        assert len(done) == 1
        assert done[0].text == "Done task"

        pending = await mgr.get_items(done=False)
        assert len(pending) == 1
        assert pending[0].text == "Pending task"

    async def test_checklist_clear_done(self, mgr) -> None:
        await mgr.add_item(ChecklistItem(text="Done 1", done=True))
        await mgr.add_item(ChecklistItem(text="Done 2", done=True))
        await mgr.add_item(ChecklistItem(text="Pending", done=False))

        removed = await mgr.clear_done()
        assert removed == 2

        items = await mgr.get_items()
        assert len(items) == 1
        assert items[0].text == "Pending"


# ---------------------------------------------------------------------------
# NullVerifier tests
# ---------------------------------------------------------------------------


class TestNullVerifier:
    """Test NullVerifier no-op verification."""

    @pytest.fixture()
    def verifier(self):
        from swarmline.memory_bank.knowledge_inmemory import NullVerifier

        return NullVerifier()

    async def test_null_verifier_passes_all(self, verifier) -> None:
        criteria = [
            QualityCriterion(name="C1", description="First"),
            QualityCriterion(name="C2", description="Second"),
        ]

        result = await verifier.verify(criteria)
        assert len(result) == 2
        assert all(c.met is True for c in result)
        assert all(c.evidence != "" for c in result)

    async def test_null_verifier_suggest_returns_empty(self, verifier) -> None:
        suggestions = await verifier.suggest_criteria("Some plan content")
        assert suggestions == []
