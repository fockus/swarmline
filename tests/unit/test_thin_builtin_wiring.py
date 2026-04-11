"""TDD RED: ThinRuntime wiring of built-in tools.

Verifies that ThinRuntime integrates builtin_tools when sandbox is provided:
- Built-in executors are registered in ToolExecutor
- Built-in specs are merged with active_tools in run()
- Aliases resolve correctly through executor
"""

from __future__ import annotations

import json
from typing import Any

import pytest


class _FakeSandboxProvider:
    """Minimal SandboxProvider for tests."""

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
            stdout = f"executed: {command}"
            stderr = ""
            exit_code = 0
            timed_out = False

        return _Result()

    async def list_dir(self, path: str = ".") -> list[str]:
        return list(self._files.keys())

    async def glob_files(self, pattern: str) -> list[str]:
        import fnmatch

        return [f for f in self._files if fnmatch.fnmatch(f, pattern)]


@pytest.fixture()
def sandbox() -> _FakeSandboxProvider:
    return _FakeSandboxProvider()


class TestThinRuntimeBuiltinWiring:
    """ThinRuntime integrates built-in tools into ToolExecutor."""

    def test_runtime_accepts_sandbox_param(self, sandbox: _FakeSandboxProvider) -> None:
        """ThinRuntime.__init__ accepts sandbox parameter."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        rt = ThinRuntime(sandbox=sandbox)
        assert rt is not None

    def test_runtime_builtin_executors_registered(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """Built-in tool executors are registered in ToolExecutor."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        rt = ThinRuntime(sandbox=sandbox)
        # Executor should recognize built-in tools
        assert rt._executor.has_tool("read_file")
        assert rt._executor.has_tool("write_file")
        assert rt._executor.has_tool("execute")
        assert rt._executor.has_tool("write_todos")
        assert rt._executor.has_tool("task")

    async def test_runtime_builtin_executor_works(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """Built-in tool can be executed through ToolExecutor."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        sandbox._files["hello.txt"] = "world"
        rt = ThinRuntime(sandbox=sandbox)

        result = await rt._executor.execute("read_file", {"path": "hello.txt"})
        data = json.loads(result)
        assert data["content"] == "world"

    async def test_runtime_without_sandbox_no_builtins(self) -> None:
        """Without sandbox, no built-in tools registered."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        rt = ThinRuntime()
        assert not rt._executor.has_tool("read_file")
        assert not rt._executor.has_tool("execute")

    async def test_runtime_builtin_react_tool_call(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """In react mode, built-in tools are callable by name."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message

        sandbox._files["data.txt"] = "test content"

        call_count = 0

        async def mock_llm(messages: Any, prompt: Any, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {
                            "name": "read_file",
                            "args": {"path": "data.txt"},
                        },
                    }
                )
            return json.dumps(
                {"type": "final", "final_message": "Done reading file"}
            )

        rt = ThinRuntime(llm_call=mock_llm, sandbox=sandbox)

        events = []
        async for event in rt.run(
            messages=[Message(role="user", content="read the file")],
            system_prompt="You are helpful",
            active_tools=[],  # No user tools — built-in should still work
            mode_hint="react",
        ):
            events.append(event)

        event_types = [e.type for e in events]
        assert "tool_call_started" in event_types
        assert "tool_call_finished" in event_types
        assert "final" in event_types

    def test_runtime_local_tools_and_builtins_coexist(
        self, sandbox: _FakeSandboxProvider
    ) -> None:
        """User local_tools and sandbox built-ins both registered."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def my_custom_tool(args: dict[str, Any]) -> str:
            return "custom result"

        rt = ThinRuntime(
            sandbox=sandbox,
            local_tools={"my_custom": my_custom_tool},
        )

        assert rt._executor.has_tool("read_file")  # built-in
        assert rt._executor.has_tool("my_custom")   # user tool
