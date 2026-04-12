"""Tests for ToolExecutor + ToolPolicy integration.

Uses REAL DefaultToolPolicy from swarmline.policy.tool_policy — no mocks for policy.
TDD RED phase: these tests define the contract for policy enforcement in ToolExecutor.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

from swarmline.hooks.dispatcher import DefaultHookDispatcher, HookResult
from swarmline.hooks.registry import HookRegistry
from swarmline.policy.tool_policy import DefaultToolPolicy, ToolPolicyInput
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
# Tests — Policy enforcement in ToolExecutor
# ---------------------------------------------------------------------------


class TestToolExecutorPolicy:
    """ToolExecutor integration with DefaultToolPolicy."""

    async def test_executor_without_policy_allows_all(self) -> None:
        """None policy → tool executes normally (backward compat)."""
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_executor_denied_tool_returns_error(self) -> None:
        """Denied tool → JSON error with reason from policy."""
        policy = DefaultToolPolicy()
        executor = ToolExecutor(
            local_tools={"bash": _echo_tool},
            tool_policy=policy,
        )
        result = await executor.execute("bash", {"cmd": "ls"})
        data = json.loads(result)
        assert "error" in data
        assert "bash" in data["error"].lower() or "запрещён" in data["error"]

    async def test_executor_allowed_tool_executes(self) -> None:
        """Allowed tool → normal execution through policy."""
        policy = DefaultToolPolicy()
        executor = ToolExecutor(
            local_tools={"my_tool": _echo_tool},
            tool_policy=policy,
        )
        result = await executor.execute("my_tool", {"msg": "hello"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hello"

    async def test_executor_policy_runs_after_pre_hook_modify(self) -> None:
        """Hook modifies args → policy checks modified args, not original."""
        modified_args_seen: dict[str, Any] = {}

        class SpyPolicy:
            """Spy policy that records what args it sees."""

            def can_use_tool(
                self,
                tool_name: str,
                input_data: dict[str, Any],
                state: ToolPolicyInput,
            ) -> Any:
                modified_args_seen.update(input_data)
                from swarmline.policy.tool_policy import PermissionAllow

                return PermissionAllow()

        async def modify_hook(**kwargs: Any) -> HookResult:
            return HookResult.modify({"a": 99, "b": 88})

        reg = HookRegistry()
        reg.on_pre_tool_use(modify_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"calc": _calc_tool},
            hook_dispatcher=dispatcher,
            tool_policy=SpyPolicy(),
        )
        await executor.execute("calc", {"a": 1, "b": 2})
        # Policy must see the MODIFIED args (99, 88), not original (1, 2)
        assert modified_args_seen == {"a": 99, "b": 88}

    async def test_executor_policy_deny_does_not_execute_tool(self) -> None:
        """Denied tool function is NEVER called."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        policy = DefaultToolPolicy()
        executor = ToolExecutor(
            local_tools={"bash": counting_tool},
            tool_policy=policy,
        )
        await executor.execute("bash", {})
        assert call_count == 0

    async def test_executor_mcp_tool_checked_by_policy(self) -> None:
        """MCP tool denied by policy when server not in active_skill_ids."""
        policy = DefaultToolPolicy()
        mock_mcp = AsyncMock()

        # mcp_servers has "real_server" but tool references "unknown_srv"
        # → active_skill_ids = ["real_server"], unknown_srv NOT in it → DENY
        executor = ToolExecutor(
            mcp_servers={"real_server": {"url": "http://localhost:9999"}},
            mcp_client=mock_mcp,
            tool_policy=policy,
        )
        result = await executor.execute("mcp__unknown_srv__do_thing", {"x": 1})
        data = json.loads(result)
        assert "error" in data
        assert "unknown_srv" in data["error"] or "не активен" in data["error"]
        mock_mcp.call_tool.assert_not_called()

    async def test_hook_block_skips_policy(self) -> None:
        """When hook blocks, policy is NOT consulted."""
        policy_called = False

        class SpyPolicy:
            def can_use_tool(self, tool_name: str, input_data: Any, state: Any) -> Any:
                nonlocal policy_called
                policy_called = True
                from swarmline.policy.tool_policy import PermissionAllow
                return PermissionAllow()

        async def block_hook(**kwargs: Any) -> HookResult:
            return HookResult.block("hook says no")

        reg = HookRegistry()
        reg.on_pre_tool_use(block_hook)
        dispatcher = DefaultHookDispatcher(reg)

        executor = ToolExecutor(
            local_tools={"my_tool": _echo_tool},
            hook_dispatcher=dispatcher,
            tool_policy=SpyPolicy(),
        )
        result = await executor.execute("my_tool", {})
        data = json.loads(result)
        assert "error" in data
        assert not policy_called

    async def test_executor_policy_allow_with_updated_input(self) -> None:
        """PermissionAllow.updated_input is used when present."""
        from swarmline.policy.tool_policy import PermissionAllow

        class UpdatingPolicy:
            def can_use_tool(self, tool_name: str, input_data: Any, state: Any) -> Any:
                return PermissionAllow(updated_input={"injected": True})

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            tool_policy=UpdatingPolicy(),
        )
        result = await executor.execute("echo", {"original": True})
        data = json.loads(result)
        assert data["echo"] == {"injected": True}
