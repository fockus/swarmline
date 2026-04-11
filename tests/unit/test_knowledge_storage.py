"""Tests for knowledge storage layer over MemoryBankProvider.

Tests DefaultKnowledgeStore, DefaultKnowledgeSearcher,
DefaultChecklistManager, DefaultProgressLog with both
FilesystemMemoryBankProvider and a dict-based mock provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.memory_bank.knowledge_checklist import DefaultChecklistManager
from swarmline.memory_bank.knowledge_progress import DefaultProgressLog
from swarmline.memory_bank.knowledge_search import DefaultKnowledgeSearcher
from swarmline.memory_bank.knowledge_store import DefaultKnowledgeStore
from swarmline.memory_bank.knowledge_types import (
    ChecklistItem,
    DocumentMeta,
    KnowledgeEntry,
)
from swarmline.memory_bank.types import MemoryBankConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class DictMemoryBankProvider:
    """Minimal dict-based mock implementing MemoryBankProvider contract."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    async def read_file(self, path: str) -> str | None:
        return self._files.get(path)

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def append_to_file(self, path: str, content: str) -> None:
        existing = self._files.get(path)
        self._files[path] = f"{existing}\n{content}" if existing else content

    async def list_files(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._files if k.startswith(prefix))

    async def delete_file(self, path: str) -> None:
        self._files.pop(path, None)


def _make_fs_provider(tmp_path: Path):
    """Create a real FilesystemMemoryBankProvider rooted in tmp_path."""
    from swarmline.memory_bank.fs_provider import FilesystemMemoryBankProvider

    config = MemoryBankConfig(root_path=tmp_path, enabled=True)
    return FilesystemMemoryBankProvider(config, user_id="u1", topic_id="t1")


@pytest.fixture(params=["fs", "dict"], ids=["filesystem", "dict-mock"])
def provider(request, tmp_path):
    """Parametrized fixture: filesystem and dict-mock providers."""
    if request.param == "fs":
        return _make_fs_provider(tmp_path)
    return DictMemoryBankProvider()


def _sample_entry(
    path: str = "notes/test.md",
    kind: str = "note",
    tags: tuple[str, ...] = ("alpha",),
    content: str = "Sample content here",
    importance: str = "medium",
) -> KnowledgeEntry:
    meta = DocumentMeta(kind=kind, tags=tags, importance=importance)
    return KnowledgeEntry(
        path=path,
        meta=meta,
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


# ===========================================================================
# DefaultKnowledgeStore
# ===========================================================================


class TestDefaultKnowledgeStore:
    """Tests for DefaultKnowledgeStore wrapping MemoryBankProvider."""

    async def test_save_and_load_roundtrip_preserves_meta_and_content(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry(
            tags=("arch", "design"), importance="high", content="Body text"
        )
        await store.save(entry)
        loaded = await store.load(entry.path)

        assert loaded is not None
        assert loaded.path == entry.path
        assert loaded.meta.kind == "note"
        assert loaded.meta.tags == ("arch", "design")
        assert loaded.meta.importance == "high"
        assert "Body text" in loaded.content

    async def test_delete_removes_entry(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry()
        await store.save(entry)
        await store.delete(entry.path)

        assert await store.load(entry.path) is None

    async def test_list_entries_all(self, provider):
        store = DefaultKnowledgeStore(provider)
        await store.save(_sample_entry("notes/a.md", kind="note"))
        await store.save(_sample_entry("plans/b.md", kind="plan"))

        entries = await store.list_entries()
        paths = {e.path for e in entries}
        assert "notes/a.md" in paths
        assert "plans/b.md" in paths

    async def test_list_entries_by_kind(self, provider):
        store = DefaultKnowledgeStore(provider)
        await store.save(_sample_entry("notes/a.md", kind="note"))
        await store.save(_sample_entry("plans/b.md", kind="plan"))

        notes = await store.list_entries(kind="note")
        assert all(e.kind == "note" for e in notes)
        assert len(notes) == 1

    async def test_exists_true_after_save(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry()
        await store.save(entry)

        assert await store.exists(entry.path) is True

    async def test_exists_false_after_delete(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry()
        await store.save(entry)
        await store.delete(entry.path)

        assert await store.exists(entry.path) is False

    async def test_index_auto_updated_on_save(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry(path="notes/idx.md", tags=("idx-tag",))
        await store.save(entry)

        raw = await provider.read_file("index.json")
        assert raw is not None
        assert "notes/idx.md" in raw
        assert "idx-tag" in raw

    async def test_index_removed_on_delete(self, provider):
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry(path="notes/idx.md")
        await store.save(entry)
        await store.delete(entry.path)

        raw = await provider.read_file("index.json")
        assert raw is not None
        assert "notes/idx.md" not in raw

    async def test_load_nonexistent_returns_none(self, provider):
        store = DefaultKnowledgeStore(provider)
        assert await store.load("nonexistent.md") is None


# ===========================================================================
# DefaultKnowledgeSearcher
# ===========================================================================


class TestDefaultKnowledgeSearcher:
    """Tests for DefaultKnowledgeSearcher wrapping MemoryBankProvider."""

    async def _setup_entries(self, provider):
        store = DefaultKnowledgeStore(provider)
        await store.save(
            _sample_entry("notes/ml.md", tags=("ml", "research"), content="Machine learning experiments")
        )
        await store.save(
            _sample_entry("notes/arch.md", tags=("architecture",), content="System architecture overview")
        )
        await store.save(
            _sample_entry("plans/roadmap.md", kind="plan", tags=("roadmap",), content="Q1 roadmap plan")
        )

    async def test_search_by_text_finds_matching(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        results = await searcher.search("machine learning")
        paths = [r.path for r in results]
        assert "notes/ml.md" in paths

    async def test_search_by_text_no_match_returns_empty(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        results = await searcher.search("xyznonexistent")
        assert results == []

    async def test_search_by_tags_finds_matching(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        results = await searcher.search_by_tags(["ml"])
        paths = [r.path for r in results]
        assert "notes/ml.md" in paths

    async def test_search_by_tags_no_match_returns_empty(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        results = await searcher.search_by_tags(["nonexistent-tag"])
        assert results == []

    async def test_rebuild_index_creates_fresh_index(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        index = await searcher.rebuild_index()
        assert len(index.entries) >= 3
        assert index.version == 1

    async def test_get_index_loads_from_storage(self, provider):
        await self._setup_entries(provider)
        searcher = DefaultKnowledgeSearcher(provider)

        index = await searcher.get_index()
        assert len(index.entries) >= 3

    async def test_search_respects_top_k(self, provider):
        store = DefaultKnowledgeStore(provider)
        for i in range(5):
            await store.save(
                _sample_entry(f"notes/item{i}.md", content=f"common word item {i}")
            )
        searcher = DefaultKnowledgeSearcher(provider)

        results = await searcher.search("common word", top_k=2)
        assert len(results) <= 2


# ===========================================================================
# DefaultChecklistManager
# ===========================================================================


class TestDefaultChecklistManager:
    """Tests for DefaultChecklistManager wrapping MemoryBankProvider."""

    async def test_add_and_get_items(self, provider):
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Task A"))
        await mgr.add_item(ChecklistItem(text="Task B"))

        items = await mgr.get_items()
        assert len(items) == 2
        texts = [i.text for i in items]
        assert "Task A" in texts
        assert "Task B" in texts

    async def test_toggle_item_changes_done_status(self, provider):
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Toggle me"))

        result = await mgr.toggle_item("Toggle")
        assert result is True

        items = await mgr.get_items()
        assert items[0].done is True

    async def test_toggle_nonexistent_returns_false(self, provider):
        mgr = DefaultChecklistManager(provider)
        result = await mgr.toggle_item("Nonexistent")
        assert result is False

    async def test_filter_done_items(self, provider):
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Done task", done=True))
        await mgr.add_item(ChecklistItem(text="Pending task", done=False))

        done = await mgr.get_items(done=True)
        assert len(done) == 1
        assert done[0].text == "Done task"

        pending = await mgr.get_items(done=False)
        assert len(pending) == 1
        assert pending[0].text == "Pending task"

    async def test_clear_done_removes_completed(self, provider):
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Keep", done=False))
        await mgr.add_item(ChecklistItem(text="Remove", done=True))

        removed = await mgr.clear_done()
        assert removed == 1

        items = await mgr.get_items()
        assert len(items) == 1
        assert items[0].text == "Keep"

    async def test_markdown_roundtrip(self, provider):
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Item one", done=False))
        await mgr.add_item(ChecklistItem(text="Item two", done=True))

        raw = await provider.read_file("checklist.md")
        assert raw is not None
        assert "- [ ] Item one" in raw
        assert "- [x] Item two" in raw

        # Reload from persisted markdown
        mgr2 = DefaultChecklistManager(provider)
        items = await mgr2.get_items()
        assert len(items) == 2


# ===========================================================================
# DefaultProgressLog
# ===========================================================================


class TestDefaultProgressLog:
    """Tests for DefaultProgressLog wrapping MemoryBankProvider."""

    async def test_append_and_get_recent(self, provider):
        log = DefaultProgressLog(provider)
        await log.append("First entry", timestamp=False)
        await log.append("Second entry", timestamp=False)

        recent = await log.get_recent(n=5)
        assert len(recent) == 2
        assert "First entry" in recent[0]
        assert "Second entry" in recent[1]

    async def test_get_all_returns_full_log(self, provider):
        log = DefaultProgressLog(provider)
        await log.append("Entry A", timestamp=False)
        await log.append("Entry B", timestamp=False)

        full = await log.get_all()
        assert "Entry A" in full
        assert "Entry B" in full

    async def test_timestamp_added_when_enabled(self, provider):
        log = DefaultProgressLog(provider)
        await log.append("Timestamped entry")

        recent = await log.get_recent(n=1)
        assert len(recent) == 1
        # Timestamp format: [YYYY-MM-DD HH:MM]
        assert recent[0].startswith("[")
        assert "] Timestamped entry" in recent[0]

    async def test_get_recent_limits_results(self, provider):
        log = DefaultProgressLog(provider)
        for i in range(10):
            await log.append(f"Entry {i}", timestamp=False)

        recent = await log.get_recent(n=3)
        assert len(recent) == 3
        assert "Entry 7" in recent[0]
        assert "Entry 9" in recent[2]

    async def test_get_recent_empty_log_returns_empty(self, provider):
        log = DefaultProgressLog(provider)
        recent = await log.get_recent()
        assert recent == []


# ===========================================================================
# Multi-backend: dict-mock provider proves backend-agnostic
# ===========================================================================


class TestWorksWithAnyProvider:
    """Verify all implementations work with a simple dict-based mock provider."""

    async def test_store_with_dict_provider(self):
        provider = DictMemoryBankProvider()
        store = DefaultKnowledgeStore(provider)
        entry = _sample_entry()
        await store.save(entry)
        loaded = await store.load(entry.path)
        assert loaded is not None
        assert loaded.meta.kind == "note"

    async def test_searcher_with_dict_provider(self):
        provider = DictMemoryBankProvider()
        store = DefaultKnowledgeStore(provider)
        await store.save(_sample_entry(content="hello world"))
        searcher = DefaultKnowledgeSearcher(provider)
        results = await searcher.search("hello")
        assert len(results) >= 1

    async def test_checklist_with_dict_provider(self):
        provider = DictMemoryBankProvider()
        mgr = DefaultChecklistManager(provider)
        await mgr.add_item(ChecklistItem(text="Test"))
        items = await mgr.get_items()
        assert len(items) == 1

    async def test_progress_with_dict_provider(self):
        provider = DictMemoryBankProvider()
        log = DefaultProgressLog(provider)
        await log.append("Test entry", timestamp=False)
        recent = await log.get_recent()
        assert len(recent) == 1
