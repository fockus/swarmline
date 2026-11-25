"""Tests for ToolExecutor + ToolPolicy integration.

Uses REAL DefaultToolPolicy from swarmline.policy.tool_policy — no mocks for policy.
TDD RED phase: these tests define the contract for policy enforcement in ToolExecutor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# I-098b — can_use_tool callback (claude-agent-sdk-compatible permission gate)
# ---------------------------------------------------------------------------


@dataclass
class _ObjectPermissionAllow:
    """Object-shaped allow result (mirrors claude_agent_sdk.PermissionResultAllow)."""

    behavior: str = "allow"
    updated_input: dict[str, Any] | None = None


@dataclass
class _ObjectPermissionDeny:
    """Object-shaped deny result (mirrors claude_agent_sdk.PermissionResultDeny)."""

    behavior: str = "deny"
    message: str = ""


class TestToolExecutorCanUseTool:
    """ToolExecutor integration with the AgentConfig.can_use_tool callback."""

    async def test_executor_without_callback_allows_all(self) -> None:
        """No callback → tool executes normally (backward compat)."""
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute("echo", {"msg": "hi"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_callback_deny_dict_returns_error_and_skips_execution(self) -> None:
        """Dict-shaped deny result → JSON error, tool NOT executed."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        async def deny_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return {"behavior": "deny", "message": "no thanks"}

        executor = ToolExecutor(
            local_tools={"bash": counting_tool},
            can_use_tool=deny_callback,
        )
        result = await executor.execute("bash", {"cmd": "ls"})
        data = json.loads(result)
        assert "error" in data
        assert "no thanks" in data["error"]
        assert call_count == 0

    async def test_callback_deny_object_returns_error_and_skips_execution(
        self,
    ) -> None:
        """Object-shaped deny result (``.behavior``/``.message``) is handled too."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        async def deny_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return _ObjectPermissionDeny(message="object says no")

        executor = ToolExecutor(
            local_tools={"bash": counting_tool},
            can_use_tool=deny_callback,
        )
        result = await executor.execute("bash", {"cmd": "ls"})
        data = json.loads(result)
        assert "error" in data
        assert "object says no" in data["error"]
        assert call_count == 0

    async def test_callback_allow_dict_executes_normally(self) -> None:
        """Dict-shaped allow result → tool executes."""

        async def allow_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return {"behavior": "allow"}

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            can_use_tool=allow_callback,
        )
        result = await executor.execute("echo", {"msg": "hello"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hello"

    async def test_callback_allow_object_executes_normally(self) -> None:
        """Object-shaped allow result (``.behavior``) → tool executes."""

        async def allow_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return _ObjectPermissionAllow()

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            can_use_tool=allow_callback,
        )
        result = await executor.execute("echo", {"msg": "hello"})
        data = json.loads(result)
        assert data["echo"]["msg"] == "hello"

    async def test_callback_allow_with_updated_input_substitutes_args_dict(
        self,
    ) -> None:
        """Dict-shaped allow + updated_input → tool receives substituted args."""

        async def allow_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return {"behavior": "allow", "updated_input": {"injected": True}}

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            can_use_tool=allow_callback,
        )
        result = await executor.execute("echo", {"original": True})
        data = json.loads(result)
        assert data["echo"] == {"injected": True}

    async def test_callback_allow_with_updated_input_substitutes_args_object(
        self,
    ) -> None:
        """Object-shaped allow + updated_input → tool receives substituted args."""

        async def allow_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return _ObjectPermissionAllow(updated_input={"injected": True})

        executor = ToolExecutor(
            local_tools={"echo": _echo_tool},
            can_use_tool=allow_callback,
        )
        result = await executor.execute("echo", {"original": True})
        data = json.loads(result)
        assert data["echo"] == {"injected": True}

    async def test_policy_deny_short_circuits_before_callback_is_invoked(
        self,
    ) -> None:
        """Both tool_policy and can_use_tool present, policy denies first →
        callback must NOT be called at all."""
        callback_called = False

        async def spy_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            nonlocal callback_called
            callback_called = True
            return {"behavior": "allow"}

        policy = DefaultToolPolicy()
        executor = ToolExecutor(
            local_tools={"bash": _echo_tool},
            tool_policy=policy,
            can_use_tool=spy_callback,
        )
        result = await executor.execute("bash", {"cmd": "ls"})
        data = json.loads(result)
        assert "error" in data
        assert not callback_called

    async def test_policy_allow_then_callback_deny_skips_execution(self) -> None:
        """Policy allows, callback denies → tool still NOT executed."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        async def deny_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            return {"behavior": "deny", "message": "callback veto"}

        policy = DefaultToolPolicy(allowed_system_tools={"custom_tool"})
        executor = ToolExecutor(
            local_tools={"custom_tool": counting_tool},
            tool_policy=policy,
            can_use_tool=deny_callback,
        )
        result = await executor.execute("custom_tool", {})
        data = json.loads(result)
        assert "error" in data
        assert "callback veto" in data["error"]
        assert call_count == 0

    async def test_raising_callback_fails_closed_and_skips_execution(self) -> None:
        """Callback raises → treated as deny (fail-closed), tool NOT executed."""
        call_count = 0

        async def counting_tool(args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        async def raising_callback(
            tool_name: str, tool_input: dict[str, Any], context: Any
        ) -> Any:
            raise RuntimeError("permission backend unreachable")

        executor = ToolExecutor(
            local_tools={"echo": counting_tool},
            can_use_tool=raising_callback,
        )
        result = await executor.execute("echo", {})
        data = json.loads(result)
        assert "error" in data
        assert "permission backend unreachable" in data["error"]
        assert call_count == 0
