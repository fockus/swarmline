"""SDK Bridge - convert swarmline HookRegistry into SDK HookMatcher format.

Allows using swarmline HookRegistry to register hooks,
then converting them into a format understood by Claude Agent SDK.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import HookMatcher

from swarmline.hooks.registry import HookEntry, HookRegistry


def registry_to_sdk_hooks(
    registry: HookRegistry,
) -> dict[str, list[HookMatcher]] | None:
    """Convert swarmline HookRegistry into an SDK hooks dict.

    Returns:
        dict[HookEvent, list[HookMatcher]] for passing to ClaudeAgentOptions.hooks,
        or None if the registry is empty.
    """
    events = registry.list_events()
    if not events:
        return None

    sdk_hooks: dict[str, list[HookMatcher]] = {}

    for event_name in events:
        entries = registry.get_hooks(event_name)
        matchers = [_entry_to_matcher(entry) for entry in entries]
        sdk_hooks[event_name] = matchers

    return sdk_hooks


def _entry_to_matcher(entry: HookEntry) -> HookMatcher:
    """Convert HookEntry into an SDK HookMatcher."""
    sdk_callback = _wrap_callback(entry.callback)
    return HookMatcher(
        matcher=entry.matcher or None,
        hooks=[sdk_callback],
    )


def _wrap_callback(swarmline_callback: Any) -> Any:
    """Wrap a swarmline callback into an SDK-compatible HookCallback.

    SDK HookCallback signature: (input: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput
    Swarmline callback signature: (**kwargs) -> dict | None
    """

    async def sdk_callback(
        hook_input: dict[str, Any],
        tool_use_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Pass all hook_input fields as kwargs to the swarmline callback
        result = await swarmline_callback(**hook_input)
        if result is None:
            return {"continue_": True}
        return result

    return sdk_callback
