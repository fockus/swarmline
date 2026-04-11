"""Integration tests: wiring capabilities in CognitiaStack. Verifies chto sandbox/todo/thinking tools correctly are assembled
and kazhdaya capability includessya/vyklyuchaetsya notzavisimo.
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
        timeout_seconds=5,
        allow_host_execution=True,
    )


class TestCollectCapabilityTools:
    """Tests collect_capability_tools - merge tools from raznyh capability."""

    def test_sandbox_only(self, sandbox_config: SandboxConfig) -> None:
        """Sandbox enabled, todo disabled → sandbox tools + thinking."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sandbox = LocalSandboxProvider(sandbox_config)
        specs, _executors = collect_capability_tools(
            sandbox_provider=sandbox,
            thinking_enabled=True,
        )

        assert "bash" in specs
        assert "read" in specs
        assert "write" in specs
        assert "thinking" in specs
        assert "todo_read" not in specs
        assert "todo_write" not in specs

    def test_todo_only(self) -> None:
        """Todo enabled, sandbox disabled → todo tools + thinking."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.todo.inmemory_provider import InMemoryTodoProvider

        todo = InMemoryTodoProvider(user_id="u", topic_id="t")
        specs, _executors = collect_capability_tools(
            todo_provider=todo,
            thinking_enabled=True,
        )

        assert "todo_read" in specs
        assert "todo_write" in specs
        assert "thinking" in specs
        assert "bash" not in specs
        assert "read" not in specs

    def test_all_capabilities(self, sandbox_config: SandboxConfig) -> None:
        """Sandbox + todo + thinking -> vse tooly."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.todo.inmemory_provider import InMemoryTodoProvider
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sandbox = LocalSandboxProvider(sandbox_config)
        todo = InMemoryTodoProvider(user_id="u", topic_id="t")

        specs, executors = collect_capability_tools(
            sandbox_provider=sandbox,
            todo_provider=todo,
            thinking_enabled=True,
        )

        # Sandbox tools
        assert "bash" in specs
        assert "read" in specs
        assert "write" in specs
        assert "edit" in specs
        assert "multi_edit" in specs
        assert "ls" in specs
        assert "glob" in specs
        assert "grep" in specs
        # Todo tools
        assert "todo_read" in specs
        assert "todo_write" in specs
        # Thinking
        assert "thinking" in specs
        # Verify chto executors tozhe sobralis
        assert set(specs.keys()) == set(executors.keys())

    def test_nothing_enabled(self) -> None:
        """Vse capability disabled -> empty dicts."""
        from cognitia.bootstrap.capabilities import collect_capability_tools

        specs, executors = collect_capability_tools(thinking_enabled=False)
        assert specs == {}
        assert executors == {}

    def test_thinking_disabled(self, sandbox_config: SandboxConfig) -> None:
        """Thinking otklyuchen -> nott thinking tool."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sandbox = LocalSandboxProvider(sandbox_config)
        specs, _executors = collect_capability_tools(
            sandbox_provider=sandbox,
            thinking_enabled=False,
        )

        assert "bash" in specs
        assert "thinking" not in specs


class TestCapabilityToolsExecution:
    """Tests chto builtnye tools realno work."""

    async def test_sandbox_bash_works(self, sandbox_config: SandboxConfig) -> None:
        """bash tool from capability wiring works."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sandbox = LocalSandboxProvider(sandbox_config)
        _specs, executors = collect_capability_tools(sandbox_provider=sandbox)

        result = await executors["bash"]({"command": "echo integration"})
        data = json.loads(result)
        assert data["stdout"].strip() == "integration"

    async def test_todo_write_read_works(self) -> None:
        """todo_write -> todo_read from capability wiring works."""
        from cognitia.bootstrap.capabilities import collect_capability_tools
        from cognitia.todo.inmemory_provider import InMemoryTodoProvider

        todo = InMemoryTodoProvider(user_id="u", topic_id="t")
        _specs, executors = collect_capability_tools(todo_provider=todo)

        await executors["todo_write"](
            {
                "todos": [{"id": "1", "content": "test", "status": "pending"}],
            }
        )
        result = await executors["todo_read"]({})
        data = json.loads(result)
        assert len(data["todos"]) == 1
        assert data["todos"][0]["content"] == "test"

    async def test_thinking_works(self) -> None:
        """thinking tool from capability wiring works."""
        from cognitia.bootstrap.capabilities import collect_capability_tools

        _specs, executors = collect_capability_tools(thinking_enabled=True)

        result = await executors["thinking"](
            {
                "thought": "анализ ситуации",
                "next_steps": ["шаг 1"],
            }
        )
        data = json.loads(result)
        assert data["status"] == "thought_recorded"
