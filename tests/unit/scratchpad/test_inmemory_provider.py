"""Contract tests for InMemoryScratchpadProvider — also serve as baseline for any ScratchpadProvider."""

from __future__ import annotations

import pytest

from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
from swarmline.scratchpad.protocols import ScratchpadProvider


@pytest.fixture
def provider() -> InMemoryScratchpadProvider:
    return InMemoryScratchpadProvider()


class TestStructuralCompliance:
    def test_implements_scratchpad_provider_protocol(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        assert isinstance(provider, ScratchpadProvider)


class TestWrite:
    async def test_write_new_key_returns_entry_with_matching_fields(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        entry = await provider.write("notes", "hello world")
        assert entry.key == "notes"
        assert entry.content == "hello world"

    async def test_write_with_tags_preserves_tags(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        entry = await provider.write("notes", "content", tags=("draft", "review"))
        assert entry.tags == ("draft", "review")

    async def test_write_existing_key_upserts_content(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("notes", "v1")
        await provider.write("notes", "v2")
        entries = await provider.read(None)
        assert isinstance(entries, list) and len(entries) == 1
        assert entries[0].content == "v2"


class TestRead:
    async def test_read_none_returns_empty_list_when_empty(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        assert await provider.read(None) == []

    async def test_read_none_returns_all_entries(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "1")
        await provider.write("b", "2")
        entries = await provider.read(None)
        assert isinstance(entries, list)
        assert {e.key for e in entries} == {"a", "b"}

    async def test_read_existing_key_returns_entry(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("research", "findings")
        entry = await provider.read("research")
        assert entry is not None and not isinstance(entry, list)
        assert entry.key == "research"
        assert entry.content == "findings"

    async def test_read_missing_key_returns_none(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        assert await provider.read("missing") is None


class TestSearch:
    async def test_search_matches_content_case_insensitive(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "API design patterns")
        await provider.write("b", "other note")
        results = await provider.search("api")
        assert [e.key for e in results] == ["a"]

    async def test_search_matches_key(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("research_notes", "x")
        await provider.write("draft", "x")
        results = await provider.search("research")
        assert [e.key for e in results] == ["research_notes"]

    async def test_search_matches_tags(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "content", tags=("review",))
        await provider.write("b", "content")
        results = await provider.search("review")
        assert [e.key for e in results] == ["a"]

    async def test_search_empty_query_returns_empty(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "x")
        assert await provider.search("") == []


class TestDelete:
    async def test_delete_existing_key_returns_true(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "x")
        assert await provider.delete("a") is True
        assert await provider.read("a") is None

    async def test_delete_missing_key_returns_false(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        assert await provider.delete("missing") is False
