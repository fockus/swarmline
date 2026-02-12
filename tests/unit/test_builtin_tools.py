"""Тесты Builtin Tools — sandbox и web инструменты.

TDD: RED → GREEN → REFACTOR.
"""

from __future__ import annotations

import json

import pytest

from cognitia.tools.types import SandboxConfig


@pytest.fixture()
def sandbox_config(tmp_path) -> SandboxConfig:
    return SandboxConfig(
        root_path=str(tmp_path),
        user_id="u1",
        topic_id="t1",
        max_file_size_bytes=1024,
        timeout_seconds=5,
    )


@pytest.fixture()
async def sandbox(sandbox_config: SandboxConfig):
    from cognitia.tools.sandbox_local import LocalSandboxProvider

    return LocalSandboxProvider(sandbox_config)


@pytest.fixture()
def sandbox_tools(sandbox):
    from cognitia.tools.builtin import create_sandbox_tools

    specs, executors = create_sandbox_tools(sandbox)
    return specs, executors


class TestBashExecutor:
    """bash tool — выполнение команд."""

    async def test_bash_echo(self, sandbox_tools) -> None:
        _specs, executors = sandbox_tools
        result = await executors["bash"]({"command": "echo hello"})
        data = json.loads(result)
        assert data["stdout"].strip() == "hello"
        assert data["exit_code"] == 0

    async def test_bash_error_returns_json(self, sandbox_tools) -> None:
        _specs, executors = sandbox_tools
        result = await executors["bash"]({"command": "false"})
        data = json.loads(result)
        assert data["exit_code"] != 0

    async def test_bash_missing_command(self, sandbox_tools) -> None:
        _specs, executors = sandbox_tools
        result = await executors["bash"]({})
        data = json.loads(result)
        assert data["status"] == "error"

    def test_bash_has_spec(self, sandbox_tools) -> None:
        specs, _ = sandbox_tools
        assert "bash" in specs
        assert specs["bash"].name == "bash"


class TestReadExecutor:
    """read tool — чтение файлов."""

    async def test_read_file(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("test.txt", "content")
        _, executors = sandbox_tools
        result = await executors["read"]({"path": "test.txt"})
        data = json.loads(result)
        assert data["content"] == "content"

    async def test_read_not_found(self, sandbox_tools) -> None:
        _, executors = sandbox_tools
        result = await executors["read"]({"path": "missing.txt"})
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_read_traversal(self, sandbox_tools) -> None:
        _, executors = sandbox_tools
        result = await executors["read"]({"path": "../../etc/passwd"})
        data = json.loads(result)
        assert data["status"] == "error"


class TestWriteExecutor:
    """write tool — запись файлов."""

    async def test_write_and_read_back(self, sandbox, sandbox_tools) -> None:
        _, executors = sandbox_tools
        result = await executors["write"]({"path": "new.txt", "content": "hello"})
        data = json.loads(result)
        assert data["status"] == "ok"

        content = await sandbox.read_file("new.txt")
        assert content == "hello"

    async def test_write_size_violation(self, sandbox_tools) -> None:
        _, executors = sandbox_tools
        result = await executors["write"]({"path": "big.txt", "content": "x" * 2048})
        data = json.loads(result)
        assert data["status"] == "error"


class TestEditExecutor:
    """edit tool — замена подстроки."""

    async def test_edit_replace(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("file.py", "old_value = 1\nold_value = 2")
        _, executors = sandbox_tools

        result = await executors["edit"]({
            "path": "file.py",
            "old_string": "old_value = 1",
            "new_string": "new_value = 42",
        })
        data = json.loads(result)
        assert data["status"] == "ok"

        content = await sandbox.read_file("file.py")
        assert "new_value = 42" in content
        assert "old_value = 2" in content  # вторая строка не затронута

    async def test_edit_string_not_found(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("f.txt", "hello")
        _, executors = sandbox_tools

        result = await executors["edit"]({
            "path": "f.txt",
            "old_string": "not_here",
            "new_string": "x",
        })
        data = json.loads(result)
        assert data["status"] == "error"


class TestMultiEditExecutor:
    """multi_edit tool — несколько замен."""

    async def test_multi_edit(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("m.py", "a = 1\nb = 2\nc = 3")
        _, executors = sandbox_tools

        result = await executors["multi_edit"]({
            "path": "m.py",
            "edits": [
                {"old_string": "a = 1", "new_string": "a = 10"},
                {"old_string": "c = 3", "new_string": "c = 30"},
            ],
        })
        data = json.loads(result)
        assert data["status"] == "ok"

        content = await sandbox.read_file("m.py")
        assert "a = 10" in content
        assert "b = 2" in content
        assert "c = 30" in content


class TestLsExecutor:
    """ls tool — список файлов."""

    async def test_ls_workspace(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("a.txt", "a")
        await sandbox.write_file("b.txt", "b")
        _, executors = sandbox_tools

        result = await executors["ls"]({"path": "."})
        data = json.loads(result)
        assert sorted(data["entries"]) == ["a.txt", "b.txt"]


class TestGlobExecutor:
    """glob tool — поиск по паттерну."""

    async def test_glob_py(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("main.py", "x")
        await sandbox.write_file("readme.md", "y")
        _, executors = sandbox_tools

        result = await executors["glob"]({"pattern": "*.py"})
        data = json.loads(result)
        assert data["matches"] == ["main.py"]


class TestGrepExecutor:
    """grep tool — поиск текста."""

    async def test_grep_finds_pattern(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("code.py", "def hello():\n    pass\ndef world():\n    pass")
        _, executors = sandbox_tools

        result = await executors["grep"]({"pattern": "def \\w+", "path": "code.py"})
        data = json.loads(result)
        assert len(data["matches"]) == 2

    async def test_grep_no_match(self, sandbox, sandbox_tools) -> None:
        await sandbox.write_file("empty.txt", "nothing here")
        _, executors = sandbox_tools

        result = await executors["grep"]({"pattern": "MISSING", "path": "empty.txt"})
        data = json.loads(result)
        assert data["matches"] == []


class TestWebTools:
    """web_fetch / web_search — без WebProvider → error."""

    def test_create_web_tools_without_provider(self) -> None:
        """Без WebProvider → пустой результат."""
        from cognitia.tools.builtin import create_web_tools

        specs, executors = create_web_tools(None)
        assert specs == {}
        assert executors == {}

    async def test_web_fetch_with_mock_provider(self) -> None:
        """web_fetch с mock WebProvider."""
        from cognitia.tools.builtin import create_web_tools

        class MockWeb:
            async def fetch(self, url: str) -> str:
                return f"content of {url}"

            async def search(self, query: str, max_results: int = 5) -> list:
                return []

        _specs, executors = create_web_tools(MockWeb())
        result = await executors["web_fetch"]({"url": "https://example.com"})
        data = json.loads(result)
        assert "content of https://example.com" in data["content"]

    async def test_web_search_with_mock_provider(self) -> None:
        """web_search с mock WebProvider."""
        from cognitia.tools.builtin import create_web_tools
        from cognitia.tools.web_protocols import SearchResult

        class MockWeb:
            async def fetch(self, url: str) -> str:
                return ""

            async def search(self, query: str, max_results: int = 5) -> list:
                return [SearchResult(title="Test", url="http://test.com", snippet="snip")]

        _specs, executors = create_web_tools(MockWeb())
        result = await executors["web_search"]({"query": "test"})
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Test"


class TestAliasMap:
    """SDK-alias (Bash → bash) через alias map."""

    def test_alias_map_exists(self) -> None:
        from cognitia.tools.builtin import TOOL_ALIAS_MAP

        assert TOOL_ALIAS_MAP["Bash"] == "bash"
        assert TOOL_ALIAS_MAP["Read"] == "read"
        assert TOOL_ALIAS_MAP["Write"] == "write"
        assert TOOL_ALIAS_MAP["Edit"] == "edit"
        assert TOOL_ALIAS_MAP["MultiEdit"] == "multi_edit"
        assert TOOL_ALIAS_MAP["Glob"] == "glob"
        assert TOOL_ALIAS_MAP["Grep"] == "grep"
        assert TOOL_ALIAS_MAP["LS"] == "ls"
        assert TOOL_ALIAS_MAP["WebFetch"] == "web_fetch"
        assert TOOL_ALIAS_MAP["WebSearch"] == "web_search"
