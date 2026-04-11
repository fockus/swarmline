"""Agent basics: query, stream, and multi-turn conversation.

Demonstrates: Agent, AgentConfig, query(), stream(), conversation().
Runs in mock mode by default, so no API key is required.
Pass ``--live`` with ``ANTHROPIC_API_KEY`` to use the real thin runtime.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

from swarmline import Agent, AgentConfig
from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

_DEMO_RUNTIME_NAME = "agent_basics_mock"
_DEMO_SESSION_ID = "agent-basics-demo"


class _MockBasicsRuntime:
    """Deterministic runtime for the basics example."""

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        _ = (system_prompt, active_tools, config, mode_hint)
        reply = self._reply_for(messages)

        for token in reply.split():
            yield RuntimeEvent.assistant_delta(f"{token} ")
            await asyncio.sleep(0.005)

        yield RuntimeEvent.final(
            text=reply,
            session_id=_DEMO_SESSION_ID,
            new_messages=[Message(role="assistant", content=reply)],
        )

    def cancel(self) -> None:
        return None

    async def cleanup(self) -> None:
        return None

    @staticmethod
    def _reply_for(messages: list[Message]) -> str:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        lowered = last_user.lower()

        if "capital of france" in lowered:
            return "Paris."
        if "haiku" in lowered and "python" in lowered:
            return "Python softly hums / Clean functions guide the logic / Bugs fade into tests."
        if "my name is" in lowered:
            name = last_user.split("My name is", 1)[-1].strip().rstrip(".")
            return f"Nice to meet you, {name}."
        if "what's my name" in lowered or "what is my name" in lowered:
            remembered = _remember_name(messages)
            if remembered:
                return f"Your name is {remembered}."
            return "I do not know your name yet."
        if "one-line joke" in lowered:
            return "I told my debugger a joke, but it kept stepping over the punchline."
        if "17 * 23" in lowered:
            return "391."
        return f"You said: {last_user}"


def _remember_name(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.role != "user":
            continue
        lowered = message.content.lower()
        if "my name is" not in lowered:
            continue
        return message.content.split("My name is", 1)[-1].strip().rstrip(".")
    return None


def _mock_factory(config: RuntimeConfig | None = None, **kwargs: object) -> _MockBasicsRuntime:
    _ = (config, kwargs)
    return _MockBasicsRuntime()


def _ensure_demo_runtime_registered() -> None:
    registry = get_default_registry()
    if registry.is_registered(_DEMO_RUNTIME_NAME):
        return

    registry.register(
        _DEMO_RUNTIME_NAME,
        _mock_factory,
        capabilities=RuntimeCapabilities(
            runtime_name=_DEMO_RUNTIME_NAME,
            tier="light",
            supports_mcp=False,
            supports_provider_override=False,
        ),
    )


def _runtime_name() -> str:
    if "--live" in sys.argv:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is required for --live mode")
        return "thin"

    _ensure_demo_runtime_registered()
    return _DEMO_RUNTIME_NAME


async def main() -> None:
    runtime_name = _runtime_name()

    # --- 1. One-shot query ---
    agent = Agent(
        AgentConfig(
            system_prompt="You are a helpful assistant. Reply concisely.",
            runtime=runtime_name,
            model="sonnet",
        )
    )

    result = await agent.query("What is the capital of France?")
    print(f"Query result: {result.text}")
    print(f"Session ID: {result.session_id}")
    if result.usage:
        print(f"Tokens used: {result.usage}")

    # --- 2. Streaming response ---
    print("\nStreaming:")
    async for event in agent.stream("Write a haiku about Python"):
        if event.type == "text_delta":
            print(event.text, end="", flush=True)
        elif event.type == "tool_use_start":
            print(f"\n[Tool: {event.tool_name}]")
    print()

    # --- 3. Multi-turn conversation ---
    print("\nConversation:")
    async with agent.conversation() as conv:
        r1 = await conv.say("My name is Alice")
        print(f"Turn 1: {r1.text}")

        r2 = await conv.say("What's my name?")
        print(f"Turn 2: {r2.text}")

        print("Turn 3 (stream): ", end="")
        async for event in conv.stream("Tell me a one-line joke"):
            if event.type == "text_delta":
                print(event.text, end="", flush=True)
        print()

    # --- 4. Context manager cleanup ---
    async with Agent(
        AgentConfig(
            system_prompt="You are a math tutor.",
            runtime=runtime_name,
        )
    ) as math_agent:
        r = await math_agent.query("What is 17 * 23?")
        print(f"\nMath: {r.text}")


if __name__ == "__main__":
    asyncio.run(main())
