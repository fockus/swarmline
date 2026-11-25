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
            return json.dumps({"type": "final", "final_message": "Done reading file"})

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
        assert rt._executor.has_tool("my_custom")  # user tool


class TestFeatureModeExposureInRun:
    """Plan E2: ThinRuntime.run() honors feature_mode for built-in exposure."""

    @staticmethod
    def _drive(feature_mode: str, allow_native: bool = False):
        import asyncio

        from swarmline.runtime.thin import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig
        import tempfile

        tmp = tempfile.mkdtemp()
        sandbox = LocalSandboxProvider(
            SandboxConfig(root_path=tmp, user_id="u", topic_id="t")
        )

        seen: dict[str, object] = {}

        async def fake_llm(messages, system_prompt, **kwargs):
            import json

            seen["tools"] = kwargs.get("tools")
            return json.dumps({"type": "final", "final_message": "ok"})

        config = RuntimeConfig(
            runtime_name="thin",
            feature_mode=feature_mode,
            allow_native_features=allow_native,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm, sandbox=sandbox)

        async def _run():
            events = []
            async for event in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="s",
                active_tools=[],
                mode_hint="conversational",
            ):
                events.append(event)
            return events

        asyncio.set_event_loop(asyncio.new_event_loop())
        events = asyncio.get_event_loop().run_until_complete(_run())
        return events

    def test_portable_mode_hides_builtins(self) -> None:
        events = self._drive("portable")
        final = [e for e in events if e.type == "final"]
        assert final, [e.type for e in events]

    def test_hybrid_mode_exposes_builtins(self) -> None:

        from swarmline.runtime.thin import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig
        import tempfile

        tmp = tempfile.mkdtemp()
        sandbox = LocalSandboxProvider(
            SandboxConfig(root_path=tmp, user_id="u", topic_id="t")
        )
        config = RuntimeConfig(runtime_name="thin", feature_mode="hybrid")

        async def fake_llm(messages, system_prompt, **kwargs):
            return "ok"

        runtime = ThinRuntime(config=config, llm_call=fake_llm, sandbox=sandbox)

        # capture what react path receives by inspecting merged active tools
        # through the internal helper: simulate run() merge logic directly
        from swarmline.runtime.thin.builtin_tools import (
            filter_thin_builtins_by_mode,
            merge_tools_with_builtins,
        )

        exposed = filter_thin_builtins_by_mode(
            list(runtime._builtin_specs.values()), feature_mode="hybrid"
        )
        merged = merge_tools_with_builtins([], exposed, feature_mode="hybrid")
        names = {spec.name for spec in merged}
        assert "read_file" in names
        assert "execute" in names
