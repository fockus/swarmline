"""Tests for Memory Bank tools - TDD."""

from __future__ import annotations

import json

import pytest
from cognitia.memory_bank.types import MemoryBankConfig


@pytest.fixture()
def provider(tmp_path):
    from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

    config = MemoryBankConfig(enabled=True, root_path=tmp_path)
    return FilesystemMemoryBankProvider(config, user_id="u1", topic_id="t1")


@pytest.fixture()
def tools(provider):
    from cognitia.memory_bank.tools import create_memory_bank_tools

    return create_memory_bank_tools(provider)


class TestMemoryRead:
    async def test_read_existing(self, provider, tools) -> None:
        await provider.write_file("MEMORY.md", "# Index")
        _specs, executors = tools
        result = await executors["memory_read"]({"path": "MEMORY.md"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["content"] == "# Index"

    async def test_read_not_found(self, tools) -> None:
        _specs, executors = tools
        result = await executors["memory_read"]({"path": "missing.md"})
        data = json.loads(result)
        assert data["status"] == "not_found"

    async def test_read_empty_path(self, tools) -> None:
        _specs, executors = tools
        result = await executors["memory_read"]({"path": ""})
        data = json.loads(result)
        assert data["status"] == "error"


class TestMemoryWrite:
    async def test_write(self, provider, tools) -> None:
        _specs, executors = tools
        result = await executors["memory_write"]({"path": "test.md", "content": "hello"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert await provider.read_file("test.md") == "hello"

    async def test_write_subfolder(self, provider, tools) -> None:
        _specs, executors = tools
        await executors["memory_write"]({"path": "plans/feature.md", "content": "plan"})
        assert await provider.read_file("plans/feature.md") == "plan"


class TestMemoryAppend:
    async def test_append(self, provider, tools) -> None:
        await provider.write_file("log.md", "line1")
        _specs, executors = tools
        await executors["memory_append"]({"path": "log.md", "content": "line2"})
        content = await provider.read_file("log.md")
        assert "line1" in content
        assert "line2" in content


class TestMemoryList:
    async def test_list_all(self, provider, tools) -> None:
        await provider.write_file("a.md", "x")
        await provider.write_file("plans/b.md", "y")
        _specs, executors = tools
        result = await executors["memory_list"]({})
        data = json.loads(result)
        assert "a.md" in data["files"]
        assert "plans/b.md" in data["files"]

    async def test_list_prefix(self, provider, tools) -> None:
        await provider.write_file("plans/a.md", "x")
        await provider.write_file("notes/b.md", "y")
        _specs, executors = tools
        result = await executors["memory_list"]({"prefix": "plans/"})
        data = json.loads(result)
        assert data["files"] == ["plans/a.md"]


class TestMemoryDelete:
    async def test_delete(self, provider, tools) -> None:
        await provider.write_file("tmp.md", "x")
        _specs, executors = tools
        await executors["memory_delete"]({"path": "tmp.md"})
        assert await provider.read_file("tmp.md") is None


class TestToolSpecs:
    def test_all_specs_present(self, tools) -> None:
        specs, executors = tools
        expected = {"memory_read", "memory_write", "memory_append", "memory_list", "memory_delete"}
        assert set(specs.keys()) == expected
        assert set(executors.keys()) == expected
