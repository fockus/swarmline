"""Tests for knowledge bank tools (search, save_note, get_context)."""

from __future__ import annotations

import json

import pytest

from cognitia.memory_bank.knowledge_inmemory import (
    InMemoryKnowledgeSearcher,
    InMemoryKnowledgeStore,
)
from cognitia.memory_bank.knowledge_types import DocumentMeta, KnowledgeEntry
from cognitia.memory_bank.tools import create_knowledge_tools


@pytest.fixture()
def store() -> InMemoryKnowledgeStore:
    return InMemoryKnowledgeStore()


@pytest.fixture()
def searcher(store: InMemoryKnowledgeStore) -> InMemoryKnowledgeSearcher:
    return InMemoryKnowledgeSearcher(store)


@pytest.fixture()
def tools(
    store: InMemoryKnowledgeStore, searcher: InMemoryKnowledgeSearcher
) -> tuple:
    return create_knowledge_tools(store, searcher)


class TestKnowledgeToolSpecs:
    def test_tool_specs_have_required_fields(self, tools: tuple) -> None:
        specs, executors = tools
        assert len(specs) == 3
        assert len(executors) == 3

        for name in ("knowledge_search", "knowledge_save_note", "knowledge_get_context"):
            assert name in specs
            spec = specs[name]
            assert spec.name == name
            assert spec.description != ""
            assert isinstance(spec.parameters, dict)
            assert name in executors


class TestKnowledgeSearchTool:
    async def test_knowledge_search_finds_saved_entry(
        self, store: InMemoryKnowledgeStore, tools: tuple
    ) -> None:
        entry = KnowledgeEntry(
            path="notes/test.md",
            meta=DocumentMeta(kind="note", tags=("python",)),
            content="Python async patterns and best practices",
            size_bytes=42,
        )
        await store.save(entry)

        _, executors = tools
        result_json = await executors["knowledge_search"]({"query": "python async"})
        result = json.loads(result_json)

        assert len(result) >= 1
        assert result[0]["path"] == "notes/test.md"

    async def test_knowledge_search_empty_returns_empty(self, tools: tuple) -> None:
        _, executors = tools
        result_json = await executors["knowledge_search"]({"query": "nonexistent"})
        result = json.loads(result_json)
        assert result == []


class TestKnowledgeSaveNoteTool:
    async def test_save_note_creates_entry(
        self, store: InMemoryKnowledgeStore, tools: tuple
    ) -> None:
        _, executors = tools
        result = await executors["knowledge_save_note"]({
            "topic": "My Test Note",
            "content": "Some knowledge content",
            "tags": "python, testing",
            "importance": "high",
        })

        assert "Saved note:" in result

        # Verify entry was stored
        entries = await store.list_entries()
        assert len(entries) == 1
        assert entries[0].kind == "note"
        assert "python" in entries[0].tags
        assert "testing" in entries[0].tags

    async def test_save_note_sanitizes_topic(
        self, store: InMemoryKnowledgeStore, tools: tuple
    ) -> None:
        _, executors = tools
        result = await executors["knowledge_save_note"]({
            "topic": "Some Topic!@#",
            "content": "content",
        })

        assert "Saved note:" in result
        entries = await store.list_entries()
        assert len(entries) == 1
        # Path should not contain special chars
        assert "!" not in entries[0].path
        assert "@" not in entries[0].path


class TestKnowledgeGetContextTool:
    async def test_get_context_returns_stats(
        self, store: InMemoryKnowledgeStore, tools: tuple
    ) -> None:
        for i in range(3):
            await store.save(KnowledgeEntry(
                path=f"notes/entry-{i}.md",
                meta=DocumentMeta(kind="note", tags=(f"tag-{i}",), updated=f"2026-01-0{i+1}"),
                content=f"Content {i}",
                size_bytes=10,
            ))

        _, executors = tools
        result_json = await executors["knowledge_get_context"]({})
        result = json.loads(result_json)

        assert result["total_entries"] == 3
        assert result["by_kind"]["note"] == 3
        assert len(result["recent"]) == 3

    async def test_get_context_empty_bank(self, tools: tuple) -> None:
        _, executors = tools
        result_json = await executors["knowledge_get_context"]({})
        result = json.loads(result_json)
        assert result["total_entries"] == 0
        assert result["by_kind"] == {}
        assert result["recent"] == []
