"""Тесты FilesystemMemoryBankProvider — TDD."""

from __future__ import annotations

import pytest

from cognitia.memory_bank.types import MemoryBankConfig, MemoryBankViolation


@pytest.fixture()
def config(tmp_path) -> MemoryBankConfig:
    return MemoryBankConfig(enabled=True, root_path=tmp_path, max_file_size_bytes=1024)


@pytest.fixture()
def provider(config):
    from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

    return FilesystemMemoryBankProvider(config, user_id="u1", topic_id="t1")


class TestFSMemoryBankReadWrite:
    async def test_write_and_read(self, provider) -> None:
        await provider.write_file("MEMORY.md", "# Memory")
        content = await provider.read_file("MEMORY.md")
        assert content == "# Memory"

    async def test_read_nonexistent(self, provider) -> None:
        result = await provider.read_file("missing.md")
        assert result is None

    async def test_write_subfolder(self, provider) -> None:
        await provider.write_file("plans/2026-02-12_feature.md", "# Plan")
        content = await provider.read_file("plans/2026-02-12_feature.md")
        assert content == "# Plan"

    async def test_overwrite(self, provider) -> None:
        await provider.write_file("f.md", "old")
        await provider.write_file("f.md", "new")
        assert await provider.read_file("f.md") == "new"

    async def test_append(self, provider) -> None:
        await provider.write_file("log.md", "line1")
        await provider.append_to_file("log.md", "line2")
        content = await provider.read_file("log.md")
        assert "line1" in content
        assert "line2" in content

    async def test_append_creates_file(self, provider) -> None:
        await provider.append_to_file("new.md", "first")
        content = await provider.read_file("new.md")
        assert content == "first"


class TestFSMemoryBankListDelete:
    async def test_list_empty(self, provider) -> None:
        result = await provider.list_files()
        assert result == []

    async def test_list_all(self, provider) -> None:
        await provider.write_file("MEMORY.md", "x")
        await provider.write_file("plans/a.md", "y")
        await provider.write_file("notes/b.md", "z")
        result = await provider.list_files()
        assert "MEMORY.md" in result
        assert "plans/a.md" in result
        assert "notes/b.md" in result

    async def test_list_prefix(self, provider) -> None:
        await provider.write_file("plans/a.md", "x")
        await provider.write_file("plans/b.md", "y")
        await provider.write_file("notes/c.md", "z")
        result = await provider.list_files("plans/")
        assert sorted(result) == ["plans/a.md", "plans/b.md"]

    async def test_delete(self, provider) -> None:
        await provider.write_file("tmp.md", "x")
        await provider.delete_file("tmp.md")
        assert await provider.read_file("tmp.md") is None

    async def test_delete_nonexistent_graceful(self, provider) -> None:
        await provider.delete_file("missing.md")  # Не бросает


class TestFSMemoryBankSecurity:
    async def test_traversal_blocked(self, provider) -> None:
        with pytest.raises(MemoryBankViolation):
            await provider.read_file("../../etc/passwd")

    async def test_depth_exceeded(self, provider) -> None:
        with pytest.raises(MemoryBankViolation):
            await provider.write_file("a/b/c/deep.md", "x")

    async def test_size_limit(self, provider) -> None:
        with pytest.raises(MemoryBankViolation):
            await provider.write_file("big.md", "x" * 2048)


class TestFSMemoryBankIsolation:
    async def test_cross_user(self, config) -> None:
        from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

        p1 = FilesystemMemoryBankProvider(config, user_id="alice", topic_id="t1")
        p2 = FilesystemMemoryBankProvider(config, user_id="bob", topic_id="t1")

        await p1.write_file("secret.md", "alice-data")
        assert await p2.read_file("secret.md") is None

    async def test_cross_topic(self, config) -> None:
        from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

        p1 = FilesystemMemoryBankProvider(config, user_id="alice", topic_id="t-x")
        p2 = FilesystemMemoryBankProvider(config, user_id="alice", topic_id="t-y")

        await p1.write_file("data.md", "topic-x")
        assert await p2.read_file("data.md") is None

    async def test_isinstance_protocol(self, provider) -> None:
        from cognitia.memory_bank.protocols import MemoryBankProvider

        assert isinstance(provider, MemoryBankProvider)
