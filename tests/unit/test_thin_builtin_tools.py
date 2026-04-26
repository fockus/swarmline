"""Tests ThinRuntime built-in tools integration. TDD RED: 6 testov for built-in tools in ThinRuntime.
Stage 1.1 from swarmline-runtime-parity plana.
"""

from __future__ import annotations

import json

import pytest
from swarmline.runtime.types import ToolSpec


class _FakeSandboxProvider:
    """Minimal SandboxProvider for testov."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    async def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        return self._files[path]

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def execute(self, command: str) -> object:
        class _Result:
            stdout = f"executed: {command}"
            stderr = ""
            exit_code = 0
            timed_out = False

        return _Result()

    async def list_dir(self, path: str) -> list[str]:
        return list(self._files.keys())

    async def glob_files(self, pattern: str) -> list[str]:
        import fnmatch

        return [f for f in self._files if fnmatch.fnmatch(f, pattern)]


@pytest.fixture()
def sandbox() -> _FakeSandboxProvider:
    return _FakeSandboxProvider()


class TestThinBuiltinToolsRegistration:
    """Built-in tools are registered pri nalichii SandboxProvider."""

    def test_thin_builtin_tools_registered_by_default(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """Pri nalichii sandbox provider 9 built-in tools available."""
        from swarmline.runtime.thin.builtin_tools import create_thin_builtin_tools

        specs, executors = create_thin_builtin_tools(sandbox)

        expected_names = {
            "read_file",
            "write_file",
            "edit_file",
            "ls",
            "glob",
            "grep",
            "execute",
            "write_todos",
            "task",
        }
        assert set(specs.keys()) == expected_names
        assert set(executors.keys()) == expected_names

    def test_thin_builtin_tools_without_sandbox_empty(self) -> None:
        """Without sandbox provider -> 0 built-in tools."""
        from swarmline.runtime.thin.builtin_tools import create_thin_builtin_tools

        specs, executors = create_thin_builtin_tools(None)
        assert specs == {}
        assert executors == {}


class TestThinBuiltinToolsFeatureMode:
    """Feature mode filtratsiya built-in tools."""

    def test_thin_builtin_tools_portable_mode_excluded(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """feature_mode=portable -> 0 built-in tools in otfiltrovannom spiske."""
        from swarmline.runtime.thin.builtin_tools import (
            create_thin_builtin_tools,
            filter_thin_builtins_by_mode,
        )

        specs, _executors = create_thin_builtin_tools(sandbox)
        all_tools = list(specs.values())

        filtered = filter_thin_builtins_by_mode(all_tools, feature_mode="portable")
        assert filtered == []

    def test_thin_builtin_tools_hybrid_mode_merged(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """User tools + built-in without dubley in hybrid mode."""
        from swarmline.runtime.thin.builtin_tools import (
            create_thin_builtin_tools,
            merge_tools_with_builtins,
        )

        specs, _executors = create_thin_builtin_tools(sandbox)
        builtin_tools = list(specs.values())

        user_tools = [
            ToolSpec(
                name="my_tool", description="Custom tool", parameters={"type": "object"}
            ),
            ToolSpec(
                name="read_file",
                description="User override",
                parameters={"type": "object"},
            ),
        ]

        merged = merge_tools_with_builtins(
            user_tools, builtin_tools, feature_mode="hybrid"
        )

        names = [t.name for t in merged]
        # User tool read_file overrides built-in
        assert names.count("read_file") == 1
        assert "my_tool" in names
        # All 9 built-ins present (minus 1 overridden + user's version)
        assert len(merged) == 9 + 1  # 9 builtins + 1 custom (read_file already counted)


class TestThinBuiltinToolsExecution:
    """Execution built-in tools cherez executors."""

    async def test_thin_builtin_execute_reads_file(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """execute("read_file", {"path": "test.txt"}) returns content."""
        from swarmline.runtime.thin.builtin_tools import create_thin_builtin_tools

        sandbox._files["test.txt"] = "hello world"

        _specs, executors = create_thin_builtin_tools(sandbox)
        result = await executors["read_file"]({"path": "test.txt"})
        data = json.loads(result)
        assert data["content"] == "hello world"


class TestThinBuiltinAliases:
    """Deepagents-sovmestimye aliasy."""

    def test_thin_builtin_aliases_resolved(self) -> None:
        """Read → read_file, Bash → execute, Write → write_file."""
        from swarmline.runtime.thin.builtin_tools import THIN_BUILTIN_ALIASES

        assert THIN_BUILTIN_ALIASES["Read"] == "read_file"
        assert THIN_BUILTIN_ALIASES["Write"] == "write_file"
        assert THIN_BUILTIN_ALIASES["Edit"] == "edit_file"
        assert THIN_BUILTIN_ALIASES["Bash"] == "execute"
        assert THIN_BUILTIN_ALIASES["LS"] == "ls"
        assert THIN_BUILTIN_ALIASES["Glob"] == "glob"
        assert THIN_BUILTIN_ALIASES["Grep"] == "grep"
        assert THIN_BUILTIN_ALIASES["Task"] == "task"
        assert THIN_BUILTIN_ALIASES["TodoWrite"] == "write_todos"
