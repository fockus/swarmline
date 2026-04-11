"""TDD Red Phase: Built-in Tools for ThinRuntime (Phase 1.1). Tests check:
- 9 built-in tools are registered if SandboxProvider is present
- feature_mode filtering (portable/hybrid/native_first)
- Aliases are compatible with DeepAgents (Read -> read_file etc.)
- Without sandbox provider -> 0 built-in tools
- Merge user tools + built-in without duplicates Contract: swarmline.runtime.thin.builtin_tools"""

from __future__ import annotations

import json

import pytest
from swarmline.runtime.thin.builtin_tools import (
    THIN_BUILTIN_ALIASES,
    THIN_BUILTIN_TOOLS,
    create_thin_builtin_tools,
    filter_thin_builtins_by_mode,
    get_thin_builtin_specs,
    merge_tools_with_builtins,
)
from swarmline.runtime.types import ToolSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeSandboxProvider:
    """InMemory SandboxProvider for tests (without I/O)."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    async def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def execute(self, command: str) -> object:
        class _Result:
            stdout = "ok"
            stderr = ""
            exit_code = 0
            timed_out = False

        return _Result()

    async def list_dir(self, path: str = ".") -> list[str]:
        return list(self._files.keys())

    async def glob_files(self, pattern: str) -> list[str]:
        import fnmatch

        return [p for p in self._files if fnmatch.fnmatch(p, pattern)]


@pytest.fixture()
def sandbox() -> FakeSandboxProvider:
    return FakeSandboxProvider()


# ---------------------------------------------------------------------------
# Stage 1.1: Built-in Tools
# ---------------------------------------------------------------------------


class TestThinBuiltinToolsRegistration:
    """Registering built-in tools in ThinRuntime."""

    def test_thin_builtin_tools_registered_by_default(self, sandbox: FakeSandboxProvider) -> None:
        """If there is a sandbox provider 9 tools appear in active_tools."""
        specs, executors = create_thin_builtin_tools(sandbox)

        registered_names = set(specs.keys())
        assert registered_names == THIN_BUILTIN_TOOLS
        assert set(executors.keys()) == THIN_BUILTIN_TOOLS

    def test_thin_builtin_tools_without_sandbox_empty(self) -> None:
        """Without sandbox provider -> 0 built-in tools."""
        specs, executors = create_thin_builtin_tools(None)

        assert specs == {}
        assert executors == {}

    def test_thin_builtin_specs_list_has_9_items(self, sandbox: FakeSandboxProvider) -> None:
        """get_thin_builtin_specs returns exactly 9 ToolSpec."""
        specs = get_thin_builtin_specs(sandbox)
        assert len(specs) == 9
        names = {s.name for s in specs}
        assert names == THIN_BUILTIN_TOOLS


class TestThinBuiltinToolsFeatureMode:
    """Filtering built-in tools by feature_mode."""

    def test_thin_builtin_tools_portable_mode_excluded(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """feature_mode=portable -> 0 built-in tools (all filtered)."""
        specs = get_thin_builtin_specs(sandbox)
        filtered = filter_thin_builtins_by_mode(specs, feature_mode="portable")
        assert filtered == []

    def test_thin_builtin_tools_hybrid_mode_keeps_all(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """feature_mode=hybrid -> all built-in tools are saved."""
        specs = get_thin_builtin_specs(sandbox)
        filtered = filter_thin_builtins_by_mode(specs, feature_mode="hybrid")
        assert len(filtered) == 9

    def test_thin_builtin_tools_native_first_mode_keeps_all(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """feature_mode=native_first -> all built-in tools are saved."""
        specs = get_thin_builtin_specs(sandbox)
        filtered = filter_thin_builtins_by_mode(specs, feature_mode="native_first")
        assert len(filtered) == 9

    def test_thin_builtin_tools_merge_hybrid_no_duplicates(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """merge_tools_with_builtins in hybrid mode -> user + built-in without duplicates."""
        builtin_specs = get_thin_builtin_specs(sandbox)
        user_tools = [
            ToolSpec(
                name="my_tool",
                description="Custom tool",
                parameters={"type": "object"},
                is_local=True,
            ),
        ]

        merged = merge_tools_with_builtins(user_tools, builtin_specs, feature_mode="hybrid")

        names = [t.name for t in merged]
        assert "my_tool" in names
        assert "read_file" in names
        assert "execute" in names
        # 9 built-in + 1 user = 10
        assert len(merged) == 10

    def test_thin_builtin_tools_merge_portable_only_user(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """merge_tools_with_builtins in portable mode -> user tools only."""
        builtin_specs = get_thin_builtin_specs(sandbox)
        user_tools = [
            ToolSpec(name="my_tool", description="Custom", parameters={"type": "object"}),
        ]

        merged = merge_tools_with_builtins(user_tools, builtin_specs, feature_mode="portable")
        assert len(merged) == 1
        assert merged[0].name == "my_tool"


class TestThinBuiltinToolsAliases:
    """Aliases are compatible with DeepAgents."""

    def test_thin_builtin_aliases_resolved(self) -> None:
        """SDK-style aliases are mapped to canonical names."""
        assert THIN_BUILTIN_ALIASES["Read"] == "read_file"
        assert THIN_BUILTIN_ALIASES["Write"] == "write_file"
        assert THIN_BUILTIN_ALIASES["Bash"] == "execute"
        assert THIN_BUILTIN_ALIASES["Edit"] == "edit_file"
        assert THIN_BUILTIN_ALIASES["Glob"] == "glob"
        assert THIN_BUILTIN_ALIASES["Grep"] == "grep"
        assert THIN_BUILTIN_ALIASES["LS"] == "ls"
        assert THIN_BUILTIN_ALIASES["Task"] == "task"
        assert THIN_BUILTIN_ALIASES["TodoWrite"] == "write_todos"

    def test_thin_builtin_aliases_cover_deepagents_set(self) -> None:
        """All DeepAgents aliases have mapping in THIN_BUILTIN_ALIASES."""
        from swarmline.runtime.deepagents_builtins import DEEPAGENTS_NATIVE_BUILTIN_ALIASES

        for alias, canonical in DEEPAGENTS_NATIVE_BUILTIN_ALIASES.items():
            assert alias in THIN_BUILTIN_ALIASES, f"Missing alias: {alias}"
            assert THIN_BUILTIN_ALIASES[alias] == canonical


class TestThinBuiltinToolsExecution:
    """Execution built-in tools via executors."""

    @pytest.mark.asyncio
    async def test_thin_builtin_execute_reads_file(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """read_file executor returns the contents of the file."""
        sandbox._files["test.txt"] = "hello world"

        _specs, executors = create_thin_builtin_tools(sandbox)
        result = await executors["read_file"]({"path": "test.txt"})

        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_thin_builtin_execute_bash(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """execute (bash) executor returns result commands."""
        _specs, executors = create_thin_builtin_tools(sandbox)
        result = await executors["execute"]({"command": "echo test"})

        data = json.loads(result)
        assert data["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_thin_builtin_write_todos(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """write_todos executor saves todo list."""
        _specs, executors = create_thin_builtin_tools(sandbox)
        result = await executors["write_todos"]({"todos": "- [ ] Task 1\n- [x] Task 2"})

        data = json.loads(result)
        assert data["status"] == "ok"
        assert sandbox._files[".todos.md"] == "- [ ] Task 1\n- [x] Task 2"

    @pytest.mark.asyncio
    async def test_thin_builtin_task_executor(
        self, sandbox: FakeSandboxProvider
    ) -> None:
        """task executor responds ok."""
        _specs, executors = create_thin_builtin_tools(sandbox)
        result = await executors["task"]({"description": "Test task"})

        data = json.loads(result)
        assert data["status"] == "ok"
