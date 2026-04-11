"""Coverage tests: memory_bank/tools.py - all 5 tool executors + edge cases."""

from __future__ import annotations

import json

from swarmline.memory_bank.tools import create_memory_bank_tools


class InMemoryProvider:
    """InMemory MemoryBankProvider for tests."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    async def read_file(self, path: str) -> str | None:
        return self._files.get(path)

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def append_to_file(self, path: str, content: str) -> None:
        self._files[path] = self._files.get(path, "") + content

    async def list_files(self, prefix: str = "") -> list[str]:
        return [p for p in sorted(self._files) if p.startswith(prefix)]

    async def delete_file(self, path: str) -> None:
        self._files.pop(path, None)


class ErrorProvider:
    """Provider that raises on all operations."""

    async def read_file(self, path: str) -> str | None:
        raise IOError("disk error")

    async def write_file(self, path: str, content: str) -> None:
        raise IOError("disk error")

    async def append_to_file(self, path: str, content: str) -> None:
        raise IOError("disk error")

    async def list_files(self, prefix: str = "") -> list[str]:
        raise IOError("disk error")

    async def delete_file(self, path: str) -> None:
        raise IOError("disk error")


class TestMemoryRead:
    """memory_read tool."""

    async def test_read_existing_file(self) -> None:
        provider = InMemoryProvider()
        provider._files["STATUS.md"] = "# Status"
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_read"]({"path": "STATUS.md"}))
        assert result["status"] == "ok"
        assert result["content"] == "# Status"

    async def test_read_missing_file(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_read"]({"path": "missing.md"}))
        assert result["status"] == "not_found"

    async def test_read_empty_path(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_read"]({"path": ""}))
        assert result["status"] == "error"

    async def test_read_error(self) -> None:
        _, executors = create_memory_bank_tools(ErrorProvider())
        result = json.loads(await executors["memory_read"]({"path": "x"}))
        assert result["status"] == "error"


class TestMemoryWrite:
    """memory_write tool."""

    async def test_write_file(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_write"]({"path": "a.md", "content": "hi"}))
        assert result["status"] == "ok"
        assert provider._files["a.md"] == "hi"

    async def test_write_empty_path(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_write"]({"path": "", "content": "x"}))
        assert result["status"] == "error"

    async def test_write_error(self) -> None:
        _, executors = create_memory_bank_tools(ErrorProvider())
        result = json.loads(await executors["memory_write"]({"path": "x", "content": "y"}))
        assert result["status"] == "error"


class TestMemoryAppend:
    """memory_append tool."""

    async def test_append_to_file(self) -> None:
        provider = InMemoryProvider()
        provider._files["log.md"] = "line1\n"
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_append"]({"path": "log.md", "content": "line2\n"}))
        assert result["status"] == "ok"
        assert provider._files["log.md"] == "line1\nline2\n"

    async def test_append_empty_path(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_append"]({"path": "", "content": "x"}))
        assert result["status"] == "error"

    async def test_append_error(self) -> None:
        _, executors = create_memory_bank_tools(ErrorProvider())
        result = json.loads(await executors["memory_append"]({"path": "x", "content": "y"}))
        assert result["status"] == "error"


class TestMemoryList:
    """memory_list tool."""

    async def test_list_all(self) -> None:
        provider = InMemoryProvider()
        provider._files = {"a.md": "", "plans/b.md": "", "notes/c.md": ""}
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_list"]({}))
        assert result["status"] == "ok"
        assert len(result["files"]) == 3

    async def test_list_with_prefix(self) -> None:
        provider = InMemoryProvider()
        provider._files = {"a.md": "", "plans/b.md": "", "plans/c.md": ""}
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_list"]({"prefix": "plans/"}))
        assert result["status"] == "ok"
        assert len(result["files"]) == 2

    async def test_list_error(self) -> None:
        _, executors = create_memory_bank_tools(ErrorProvider())
        result = json.loads(await executors["memory_list"]({}))
        assert result["status"] == "error"


class TestMemoryDelete:
    """memory_delete tool."""

    async def test_delete_file(self) -> None:
        provider = InMemoryProvider()
        provider._files["old.md"] = "content"
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_delete"]({"path": "old.md"}))
        assert result["status"] == "ok"
        assert "old.md" not in provider._files

    async def test_delete_empty_path(self) -> None:
        provider = InMemoryProvider()
        _, executors = create_memory_bank_tools(provider)
        result = json.loads(await executors["memory_delete"]({"path": ""}))
        assert result["status"] == "error"

    async def test_delete_error(self) -> None:
        _, executors = create_memory_bank_tools(ErrorProvider())
        result = json.loads(await executors["memory_delete"]({"path": "x"}))
        assert result["status"] == "error"


class TestCreateMemoryBankToolsSpecs:
    """create_memory_bank_tools returns 5 specs and 5 executors."""

    def test_returns_five_specs_and_executors(self) -> None:
        provider = InMemoryProvider()
        specs, executors = create_memory_bank_tools(provider)
        assert len(specs) == 5
        assert len(executors) == 5
        for name in ["memory_read", "memory_write", "memory_append", "memory_list", "memory_delete"]:
            assert name in specs
            assert name in executors
            assert specs[name].name == name
