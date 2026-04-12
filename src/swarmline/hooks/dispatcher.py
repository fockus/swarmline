"""HookDispatcher — dispatches hook events to registered callbacks.

HookDispatcher Protocol (4 async methods, ISP-compliant) + DefaultHookDispatcher
that iterates HookRegistry entries with fnmatch-based tool name filtering.

Fail-open policy: any exception in a hook callback is logged as a warning
and execution continues normally (never blocks the agent due to a broken hook).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Literal, Protocol, runtime_checkable

from swarmline.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookResult:
    """Immutable result of a pre-tool hook dispatch.

    Use factory class methods instead of direct construction:
        HookResult.allow()
        HookResult.block("reason")
        HookResult.modify({"key": "value"})
    """

    action: Literal["allow", "block", "modify"]
    modified_input: dict[str, Any] | None = None
    message: str | None = None

    @classmethod
    def allow(cls) -> HookResult:
        """Allow tool execution without changes."""
        return cls(action="allow")

    @classmethod
    def block(cls, message: str) -> HookResult:
        """Block tool execution with a reason message."""
        return cls(action="block", message=message)

    @classmethod
    def modify(cls, modified_input: dict[str, Any]) -> HookResult:
        """Allow tool execution with modified input."""
        return cls(action="modify", modified_input=modified_input)


@runtime_checkable
class HookDispatcher(Protocol):
    """Port for dispatching hook events (ISP: exactly 4 methods).

    Implementations iterate registered hooks, apply matcher filtering,
    and aggregate results. Must be fail-open on callback exceptions.
    """

    async def dispatch_pre_tool(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> HookResult: ...

    async def dispatch_post_tool(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> str | None: ...

    async def dispatch_stop(self, result_text: str) -> None: ...

    async def dispatch_user_prompt(self, prompt: str) -> str: ...


class DefaultHookDispatcher:
    """Default implementation of HookDispatcher backed by HookRegistry.

    Iterates hooks in registration order. Uses fnmatch for tool name matching.
    Fail-open: any exception in a callback → log warning, continue execution.
    """

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry

    async def dispatch_pre_tool(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> HookResult:
        """Dispatch PreToolUse hooks. First block wins; modify chains.

        Multiple modify hooks accumulate: each receives the already-modified
        input from the previous hook. Block stops iteration immediately.

        Supports both HookResult returns and legacy dict format
        (``{"decision": "block", "reason": ...}`` / ``{"continue_": True}``).
        """
        current_input = tool_input
        was_modified = False
        for entry in self._registry.get_hooks("PreToolUse"):
            if entry.matcher and not fnmatch(tool_name, entry.matcher):
                continue
            try:
                result = await entry.callback(
                    tool_name=tool_name, tool_input=current_input
                )
            except Exception:
                logger.warning(
                    "PreToolUse hook %r raised an exception, allowing execution (fail-open)",
                    entry.callback.__name__,
                    exc_info=True,
                )
                continue

            hook_result = self._coerce_pre_tool_result(result)
            if hook_result.action == "block":
                return hook_result
            if hook_result.action == "modify" and hook_result.modified_input is not None:
                current_input = hook_result.modified_input
                was_modified = True

        if was_modified:
            return HookResult.modify(current_input)
        return HookResult.allow()

    @staticmethod
    def _coerce_pre_tool_result(result: Any) -> HookResult:
        """Convert callback return value to HookResult.

        Handles: HookResult (pass-through), dict (legacy SDK format), None (allow).
        """
        if isinstance(result, HookResult):
            return result
        if isinstance(result, dict):
            if result.get("decision") == "block":
                return HookResult.block(result.get("reason", "Blocked by hook"))
            if result.get("continue_"):
                return HookResult.allow()
        return HookResult.allow()

    async def dispatch_post_tool(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> str | None:
        """Dispatch PostToolUse hooks. Returns modified output or None.

        Supports both string returns and legacy dict format
        (``{"tool_result": "..."}`` / ``{"continue_": True}``).
        """
        modified: str | None = None
        for entry in self._registry.get_hooks("PostToolUse"):
            if entry.matcher and not fnmatch(tool_name, entry.matcher):
                continue
            try:
                hook_result = await entry.callback(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output,
                )
            except Exception:
                logger.warning(
                    "PostToolUse hook %r raised an exception, skipping (fail-open)",
                    entry.callback.__name__,
                    exc_info=True,
                )
                continue

            coerced = self._coerce_post_tool_result(hook_result)
            if coerced is not None:
                modified = coerced
        return modified

    @staticmethod
    def _coerce_post_tool_result(result: Any) -> str | None:
        """Convert callback return value to str | None.

        Handles: str (pass-through), dict with tool_result key (legacy),
        dict with continue_ (no-op), None (no-op).
        """
        if result is None:
            return None
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if result.get("continue_"):
                return None
            if "tool_result" in result:
                return str(result["tool_result"])
        return None

    async def dispatch_stop(self, result_text: str) -> None:
        """Dispatch Stop hooks. Calls all hooks; exceptions are swallowed."""
        for entry in self._registry.get_hooks("Stop"):
            try:
                await entry.callback(result_text=result_text)
            except Exception:
                logger.warning(
                    "Stop hook %r raised an exception, continuing (fail-open)",
                    entry.callback.__name__,
                    exc_info=True,
                )

    async def dispatch_user_prompt(self, prompt: str) -> str:
        """Dispatch UserPromptSubmit hooks. Chains prompt transformations."""
        current = prompt
        for entry in self._registry.get_hooks("UserPromptSubmit"):
            try:
                result = await entry.callback(prompt=current)
            except Exception:
                logger.warning(
                    "UserPromptSubmit hook %r raised an exception, keeping current prompt (fail-open)",
                    entry.callback.__name__,
                    exc_info=True,
                )
                continue
            if isinstance(result, str):
                current = result
        return current
