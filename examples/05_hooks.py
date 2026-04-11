"""Lifecycle hooks: intercept tool calls before and after execution.

Demonstrates: HookRegistry, on_pre_tool_use, on_post_tool_use, on_stop, merge.
No API keys required.
"""

import asyncio

from swarmline.hooks.registry import HookRegistry


async def audit_pre_tool(event: dict) -> dict:
    """Log every tool call before it runs."""
    tool_name = event.get("tool_name", "unknown")
    print(f"  [PRE]  About to call tool: {tool_name}")
    return event  # return unchanged to allow


async def audit_post_tool(event: dict) -> dict:
    """Log tool results after execution."""
    tool_name = event.get("tool_name", "unknown")
    output = str(event.get("output", ""))[:60]
    print(f"  [POST] Tool {tool_name} returned: {output}")
    return event


async def block_dangerous(event: dict) -> dict:
    """Block specific tools by returning a modified event."""
    tool_name = event.get("tool_name", "")
    if tool_name in ("rm", "sudo", "drop_table"):
        print(f"  [BLOCK] Denied dangerous tool: {tool_name}")
        event["blocked"] = True
    return event


async def on_stop(event: dict) -> dict:
    """Cleanup when agent stops."""
    print("  [STOP] Agent session ended.")
    return event


async def main() -> None:
    # 1. Create hook registry and register callbacks
    hooks = HookRegistry()
    hooks.on_pre_tool_use(audit_pre_tool)
    hooks.on_pre_tool_use(block_dangerous)
    hooks.on_post_tool_use(audit_post_tool)
    hooks.on_stop(on_stop)

    print("Registered events:", hooks.list_events())

    # 2. Simulate tool call events
    print("\nSimulated tool call (safe):")
    pre_entries = hooks.get_hooks("PreToolUse")
    event = {"tool_name": "get_weather", "args": {"city": "Berlin"}}
    for entry in pre_entries:
        event = await entry.callback(event)

    print("\nSimulated tool call (dangerous):")
    event = {"tool_name": "rm", "args": {"path": "/"}}
    for entry in pre_entries:
        event = await entry.callback(event)
    print(f"  Blocked: {event.get('blocked', False)}")

    # 3. Merge registries (e.g., from middleware)
    async def passthrough_hook(event: dict) -> dict:
        """A no-op hook that just passes the event through."""
        return event

    extra_hooks = HookRegistry()
    extra_hooks.on_post_tool_use(passthrough_hook)

    merged = hooks.merge(extra_hooks)
    print(f"\nMerged hook events: {merged.list_events()}")

    # 4. Matcher-based hooks (only fire for specific tools)
    targeted = HookRegistry()
    targeted.on_pre_tool_use(
        lambda e: print(f"  [MATCH] Bash tool: {e}") or e,
        matcher="bash",
    )
    print("\nTargeted hooks registered for 'bash' tool.")


if __name__ == "__main__":
    asyncio.run(main())
