"""Custom runtime: register your own execution engine via RuntimeRegistry.

Demonstrates: RuntimeRegistry.register(), custom runtime factory, capabilities.
No API keys required.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.registry import RuntimeRegistry
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class EchoRuntime:
    """A trivial runtime that echoes user messages back -- for demonstration."""

    def __init__(self, config: RuntimeConfig | None = None, prefix: str = "Echo") -> None:
        self._prefix = prefix

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        last_user_msg = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "No message",
        )
        response = f"[{self._prefix}] {last_user_msg}"

        # Stream token by token
        for word in response.split():
            yield RuntimeEvent.assistant_delta(text=word + " ")

        yield RuntimeEvent.final(text=response, new_messages=[])

    def cancel(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass

    async def __aenter__(self) -> "EchoRuntime":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()


def echo_factory(config: RuntimeConfig | None = None, **kwargs: Any) -> EchoRuntime:
    """Factory function for RuntimeRegistry."""
    prefix = kwargs.get("prefix", "Echo")
    return EchoRuntime(config=config, prefix=prefix)


async def main() -> None:
    # 1. Create a fresh registry
    registry = RuntimeRegistry()

    # 2. Register custom runtime with capabilities
    echo_capabilities = RuntimeCapabilities(
        runtime_name="echo",
        tier="light",
        supports_mcp=False,
        supports_provider_override=False,
    )
    registry.register("echo", echo_factory, capabilities=echo_capabilities)
    print(f"Registered runtimes: {registry.list_available()}")
    print(f"Echo registered: {registry.is_registered('echo')}")

    # 3. Get capabilities
    caps = registry.get_capabilities("echo")
    print(f"Echo tier: {caps.tier}")
    print(f"Echo flags: {caps.enabled_flags()}")

    # 4. Create and use the runtime
    factory_fn = registry.get("echo")
    # RuntimeConfig validates runtime_name via get_valid_runtime_names().
    # Pass None since our custom runtime doesn't need it.
    runtime = factory_fn(config=None)

    messages = [Message(role="user", content="Hello, custom runtime!")]
    print("\nRunning echo runtime:")
    async for event in runtime.run(
        messages=messages,
        system_prompt="You are an echo bot.",
        active_tools=[],
    ):
        if event.is_text:
            print(f"  Token: {event.text}")
        elif event.is_final:
            print(f"  Final: {event.data.get('text', '')}")

    # 5. Unregister
    registry.unregister("echo")
    print(f"\nAfter unregister: {registry.list_available()}")

    # 6. Entry point plugins (for pip-installable runtimes)
    print("\n# To make your runtime pip-installable, add to pyproject.toml:")
    print("# [project.entry-points.'swarmline.runtimes']")
    print("# my_runtime = 'my_package.runtime:factory_fn'")


if __name__ == "__main__":
    asyncio.run(main())
