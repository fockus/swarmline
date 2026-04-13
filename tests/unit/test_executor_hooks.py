"""Tests for ToolExecutor + HookDispatcher integration.

Uses REAL HookRegistry + DefaultHookDispatcher — no mocks for hook dispatch.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock


from swarmline.hooks.dispatcher import DefaultHookDispatcher, HookResult
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.thin.executor import ToolExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _echo_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Simple tool that echoes input."""
    return {"echo": args}


async def _calc_tool(a: int, b: int) -> dict[str, Any]:
    """Simple calc tool (kwargs style)."""
    return {"sum": a + b}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolExecutorHooks:
    """ToolExecutor integration with HookDispatcher."""

    async def test_executor_without_dispatcher_works_as_before(self) -> None:
        """No dispatcher → execute behaves identically to before (backward compat)."""
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_executor_pre_tool_allow_proceeds_normally(self) -> None:
        """Pre-tool hook returns allow → tool executes normally."""

        async def allow_hook(**kwargs: Any) -> HookResult:
            return HookResult.allow()

        reg = HookRegistry()
        reg.on_pre_tool_use(allow_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            hook_dispatcher=dispatcher,
        )
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_executor_pre_tool_block_returns_error(self) -> None:
        """Pre-tool hook returns block → JSON error with message, tool NOT called."""

        async def block_hook(**kwargs: Any) -> HookResult:
            return HookResult.block("security: tool blocked")

        reg = HookRegistry()
        reg.on_pre_tool_use(block_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            hook_dispatcher=dispatcher,
        )
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert "error" in data
        assert "security: tool blocked" in data["error"]

    async def test_executor_pre_tool_block_does_not_execute_tool(self) -> None:
        """Verify that when blocked, the tool function is NEVER called."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        async def block_hook(**kwargs: Any) -> HookResult:
            return HookResult.block("blocked")

        reg = HookRegistry()
        reg.on_pre_tool_use(block_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"counting": counting_tool},
            hook_dispatcher=dispatcher,
        )
        await executor.execute("counting", {})
        assert call_count == 0

    async def test_executor_pre_tool_modify_passes_modified_args(self) -> None:
        """Pre-tool hook returns modify → tool receives modified args."""

        async def modify_hook(**kwargs: Any) -> HookResult:
            return HookResult.modify({"a": 10, "b": 20})

        reg = HookRegistry()
        reg.on_pre_tool_use(modify_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"calc": _calc_tool},
            hook_dispatcher=dispatcher,
        )
        result = await executor.execute("calc", {"a": 1, "b": 2})
        data = json.loads(result)
        assert data["sum"] == 30  # 10 + 20, not 1 + 2

    async def test_executor_post_tool_modifies_output(self) -> None:
        """Post-tool hook transforms output string."""

        async def post_hook(**kwargs: Any) -> str | None:
            return '{"replaced": true}'

        reg = HookRegistry()
        reg.on_post_tool_use(post_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            hook_dispatcher=dispatcher,
        )
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert data["replaced"] is True

    async def test_executor_mcp_tool_also_triggers_hooks(self) -> None:
        """MCP tools also fire pre/post hooks."""

        async def block_mcp(**kwargs: Any) -> HookResult:
            return HookResult.block("mcp blocked")

        reg = HookRegistry()
        reg.on_pre_tool_use(block_mcp, matcher="mcp__*")
        dispatcher = DefaultHookDispatcher(reg)

        mock_mcp = AsyncMock()
        executor = ToolExecutor(
            mcp_servers={"srv": {"url": "http://localhost:9999"}},
            mcp_client=mock_mcp,
            hook_dispatcher=dispatcher,
        )
        result = await executor.execute("mcp__srv__do_thing", {"x": 1})
        data = json.loads(result)
        assert "error" in data
        assert "mcp blocked" in data["error"]
        mock_mcp.call_tool.assert_not_called()
