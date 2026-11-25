"""Contract tests for create_scratchpad_tools — 4 tools with ToolSpec + executor shape."""

from __future__ import annotations

import json

import pytest

from swarmline.domain_types import ToolSpec
from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
from swarmline.scratchpad.tools import create_scratchpad_tools


@pytest.fixture
def provider() -> InMemoryScratchpadProvider:
    return InMemoryScratchpadProvider()


class TestFactoryShape:
    def test_returns_four_tools(self, provider: InMemoryScratchpadProvider) -> None:
        specs, executors = create_scratchpad_tools(provider)
        assert set(specs.keys()) == {
            "scratch_write",
            "scratch_read",
            "scratch_search",
            "scratch_delete",
        }
        assert set(executors.keys()) == set(specs.keys())

    def test_every_spec_is_toolspec_with_non_empty_description(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        specs, _ = create_scratchpad_tools(provider)
        for name, spec in specs.items():
            assert isinstance(spec, ToolSpec)
            assert spec.name == name
            assert spec.description
            assert isinstance(spec.parameters, dict)
            assert spec.parameters.get("type") == "object"


class TestScratchWriteExecutor:
    async def test_writes_entry_through_provider(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_write"](key="notes", content="hello")
        assert isinstance(result, str)
        entry = await provider.read("notes")
        assert entry is not None and not isinstance(entry, list)
        assert entry.content == "hello"

    async def test_accepts_optional_tags(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        _, executors = create_scratchpad_tools(provider)
        await executors["scratch_write"](key="notes", content="c", tags=["a", "b"])
        entry = await provider.read("notes")
        assert entry is not None and not isinstance(entry, list)
        assert entry.tags == ("a", "b")


class TestScratchReadExecutor:
    async def test_reads_all_when_no_key(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "1")
        await provider.write("b", "2")
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_read"]()
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert {e["key"] for e in parsed} == {"a", "b"}

    async def test_reads_specific_key(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "content-a")
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_read"](key="a")
        parsed = json.loads(result)
        assert parsed["key"] == "a"
        assert parsed["content"] == "content-a"

    async def test_reads_missing_key_returns_null_json(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_read"](key="missing")
        assert json.loads(result) is None


class TestScratchSearchExecutor:
    async def test_returns_matches_as_json_list(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("notes", "API design")
        await provider.write("other", "unrelated")
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_search"](query="api")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert [e["key"] for e in parsed] == ["notes"]


class TestScratchDeleteExecutor:
    async def test_delete_existing_returns_true_string(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        await provider.write("a", "x")
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_delete"](key="a")
        assert "true" in result.lower() or "deleted" in result.lower()
        assert await provider.read("a") is None

    async def test_delete_missing_surfaces_false(
        self, provider: InMemoryScratchpadProvider
    ) -> None:
        _, executors = create_scratchpad_tools(provider)
        result = await executors["scratch_delete"](key="missing")
        assert "false" in result.lower() or "not" in result.lower()
