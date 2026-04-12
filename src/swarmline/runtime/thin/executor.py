"""Executor module."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from swarmline.runtime.thin.mcp_client import (
    McpClient,
    parse_mcp_tool_name,
    resolve_mcp_server_url,
)

if TYPE_CHECKING:
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.policy.tool_policy import DefaultToolPolicy


class ToolExecutor:
    """Tool Executor implementation."""

    def __init__(
        self,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        mcp_client: McpClient | None = None,
        timeout_seconds: float = 30.0,
        hook_dispatcher: HookDispatcher | None = None,
        tool_policy: DefaultToolPolicy | None = None,
    ) -> None:
        self._local_tools = local_tools or {}
        self._mcp_servers = mcp_servers or {}
        self._timeout = timeout_seconds
        self._mcp_client = mcp_client or McpClient(timeout_seconds=timeout_seconds)
        self._hook_dispatcher = hook_dispatcher
        self._tool_policy = tool_policy

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute."""
        # Pre-tool hooks
        if self._hook_dispatcher is not None:
            hook_result = await self._hook_dispatcher.dispatch_pre_tool(tool_name, args)
            if hook_result.action == "block":
                return json.dumps(
                    {"error": f"Hook blocked: {hook_result.message}"},
                    ensure_ascii=False,
                )
            if hook_result.action == "modify" and hook_result.modified_input is not None:
                args = hook_result.modified_input

        # Policy check (after hooks, before execution)
        if self._tool_policy is not None:
            from swarmline.policy.tool_policy import (
                PermissionAllow,
                PermissionDeny,
                ToolPolicyInput,
            )

            state = ToolPolicyInput(
                tool_name=tool_name,
                input_data=args,
                active_skill_ids=list(self._mcp_servers.keys()),
                allowed_local_tools=set(self._local_tools.keys()),
            )
            decision = self._tool_policy.can_use_tool(tool_name, args, state)
            if isinstance(decision, PermissionDeny):
                return json.dumps({"error": decision.message}, ensure_ascii=False)
            if isinstance(decision, PermissionAllow) and decision.updated_input is not None:
                args = decision.updated_input

        # Local tool
        if tool_name in self._local_tools:
            result = await self._execute_local(tool_name, args)
        elif tool_name.startswith("mcp__"):
            result = await self._execute_mcp(tool_name, args)
        else:
            return json.dumps(
                {"error": f"Инструмент '{tool_name}' не найден"},
                ensure_ascii=False,
            )

        # Post-tool hooks
        if self._hook_dispatcher is not None:
            modified = await self._hook_dispatcher.dispatch_post_tool(
                tool_name, args, result
            )
            if modified is not None:
                result = modified

        return result

    async def _execute_local(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute local tool."""
        func = self._local_tools[tool_name]

        try:
            result = await asyncio.wait_for(
                self._call_func(func, args),
                timeout=self._timeout,
            )
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except TimeoutError:
            return json.dumps(
                {"error": f"Таймаут выполнения {tool_name} ({self._timeout}s)"},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {"error": f"Ошибка {tool_name}: {e}"},
                ensure_ascii=False,
            )

    @staticmethod
    async def _call_func(func: Callable[..., Any], args: dict[str, Any]) -> Any:
        """Call func."""
        call_with_kwargs = ToolExecutor._should_call_with_kwargs(func, args)

        if asyncio.iscoroutinefunction(func):
            if call_with_kwargs:
                return await func(**args)
            return await func(args)

        if call_with_kwargs:
            result = await asyncio.to_thread(func, **args)
        else:
            result = await asyncio.to_thread(func, args)
        if asyncio.iscoroutine(result):
            return await result
        return result

    @staticmethod
    def _should_call_with_kwargs(func: Callable[..., Any], args: dict[str, Any]) -> bool:
        """Should call with kwargs."""
        if hasattr(func, "__tool_definition__"):
            return True

        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return False

        params = list(signature.parameters.values())
        if not params:
            return not args

        if any(param.kind == inspect.Parameter.POSITIONAL_ONLY for param in params):
            return False

        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
            return True

        if not args:
            return not any(
                param.default is inspect.Parameter.empty
                for param in params
                if param.kind
                in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            )

        accepted_names = {
            param.name
            for param in params
            if param.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        return set(args).issubset(accepted_names)

    async def _execute_mcp(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute MCP tool via HTTP JSON-RPC."""
        parsed = self._parse_mcp_tool_name(tool_name)
        if parsed is None:
            return json.dumps(
                {"error": f"Некорректное имя MCP tool: '{tool_name}'"},
                ensure_ascii=False,
            )

        server_id, remote_tool_name = parsed
        server_url = self._resolve_server_url(server_id)
        if not server_url:
            return json.dumps(
                {"error": f"MCP server '{server_id}' не найден или не имеет URL"},
                ensure_ascii=False,
            )

        try:
            data = await self._mcp_client.call_tool(
                server_url=server_url,
                tool_name=remote_tool_name,
                arguments=args,
            )
            if isinstance(data, dict) and data.get("error"):
                return json.dumps(
                    {"error": f"MCP error: {data['error']}"},
                    ensure_ascii=False,
                    default=str,
                )
            if isinstance(data, str):
                return data
            return json.dumps(data or {}, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps(
                {"error": f"Ошибка MCP '{tool_name}': {e}"},
                ensure_ascii=False,
            )

    @staticmethod
    def _parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
        """Parse MCP__server__tool -> (server, tool)."""
        return parse_mcp_tool_name(tool_name)

    def _resolve_server_url(self, server_id: str) -> str | None:
        """Resolve server url."""
        return resolve_mcp_server_url(self._mcp_servers, server_id)

    def has_tool(self, tool_name: str) -> bool:
        """Has tool."""
        if tool_name in self._local_tools:
            return True
        parsed = self._parse_mcp_tool_name(tool_name)
        if parsed is None:
            return False
        return self._resolve_server_url(parsed[0]) is not None

    @property
    def local_tool_names(self) -> list[str]:
        """Local tool names."""
        return list(self._local_tools.keys())
