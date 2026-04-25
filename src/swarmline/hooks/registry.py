"""HookRegistry - registry of hooks for intercepting agent events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Hook types
HookCallback = Callable[..., Awaitable[Any]]


@dataclass
class HookEntry:
    """Entry in the hook registry."""

    event: str  # 'PreToolUse' | 'PostToolUse' | 'Stop' | 'UserPromptSubmit' | etc.
    callback: HookCallback
    matcher: str = ""  # Optional tool name filter


class HookRegistry:
    """Hook registry (programmatic registration for the MVP).

    Hooks are mapped to SDK HookMatcher instances when building ClaudeAgentOptions.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookEntry]] = {}

    def on_pre_tool_use(self, callback: HookCallback, matcher: str = "") -> None:
        """Register a hook before a tool call."""
        self._add("PreToolUse", callback, matcher)

    def on_post_tool_use(self, callback: HookCallback, matcher: str = "") -> None:
        """Register a hook after a tool call."""
        self._add("PostToolUse", callback, matcher)

    def on_stop(self, callback: HookCallback) -> None:
        """Register a hook on stop."""
        self._add("Stop", callback)

    def on_user_prompt(self, callback: HookCallback) -> None:
        """Register a hook when a prompt is submitted."""
        self._add("UserPromptSubmit", callback)

    def _add(self, event: str, callback: HookCallback, matcher: str = "") -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(
            HookEntry(event=event, callback=callback, matcher=matcher)
        )

    def get_hooks(self, event: str) -> list[HookEntry]:
        """Get hooks for an event."""
        return self._hooks.get(event, [])

    def list_events(self) -> list[str]:
        """All events with registered hooks."""
        return list(self._hooks.keys())

    def merge(self, other: HookRegistry) -> HookRegistry:
        """Merge hooks from another registry into a new combined registry."""
        merged = HookRegistry()
        for _event, entries in self._hooks.items():
            for entry in entries:
                merged._add(entry.event, entry.callback, entry.matcher)
        for _event, entries in other._hooks.items():
            for entry in entries:
                merged._add(entry.event, entry.callback, entry.matcher)
        return merged
