"""MockRuntime — deterministic offline runtime for tests and examples.

No API keys required. Pattern-matches the last user message against a
configurable mapping and emits a streamed reply followed by a final event.

Usage::

    from swarmline import Agent, AgentConfig
    from swarmline.testing import MockRuntime

    MockRuntime.register_default()
    agent = Agent(AgentConfig(
        system_prompt="...",
        runtime=MockRuntime.NAME,   # "mock"
    ))
    result = await agent.query("What is 17 * 23?")
    assert "391" in result.text
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping

from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# Bundled demo replies — keyed by lowercase substring of the last user message.
DEFAULT_REPLIES: Mapping[str, str] = {
    "capital of france": "Paris.",
    "haiku": (
        "Python softly hums / Clean functions guide the logic / Bugs fade into tests."
    ),
    "one-line joke": (
        "I told my debugger a joke, but it kept stepping over the punchline."
    ),
    "17 * 23": "391.",
}


class MockRuntime:
    """Deterministic mock runtime — no external dependencies.

    - Streams the reply token-by-token (one ``assistant_delta`` per word).
    - Emits a final ``RuntimeEvent.final`` with accumulated text.
    - Optional ``name_memory=True`` enables the "My name is X / what's my name?"
      conversation pattern used by the basics example.
    """

    NAME = "mock"

    def __init__(
        self,
        *,
        replies: Mapping[str, str] | None = None,
        session_id: str = "mock-session",
        name_memory: bool = True,
        delta_delay: float = 0.0,
    ) -> None:
        self._replies = dict(DEFAULT_REPLIES, **(replies or {}))
        self._session_id = session_id
        self._name_memory = name_memory
        self._delta_delay = delta_delay

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        del system_prompt, active_tools, config, mode_hint
        reply = self._reply_for(messages)
        for token in reply.split():
            yield RuntimeEvent.assistant_delta(f"{token} ")
            if self._delta_delay:
                await asyncio.sleep(self._delta_delay)
        yield RuntimeEvent.final(
            text=reply,
            session_id=self._session_id,
            new_messages=[Message(role="assistant", content=reply)],
        )

    def cancel(self) -> None:
        return None

    async def cleanup(self) -> None:
        return None

    def _reply_for(self, messages: list[Message]) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        lowered = last_user.lower()

        if self._name_memory:
            if "my name is" in lowered:
                name = last_user.split("My name is", 1)[-1].strip().rstrip(".")
                return f"Nice to meet you, {name}."
            if "what's my name" in lowered or "what is my name" in lowered:
                remembered = _remember_name(messages)
                if remembered:
                    return f"Your name is {remembered}."
                return "I do not know your name yet."

        for trigger, reply in self._replies.items():
            if trigger in lowered:
                return reply
        return f"You said: {last_user}"

    @classmethod
    def register_default(cls) -> None:
        """Register MockRuntime under name 'mock' in the default runtime registry.

        Idempotent — safe to call multiple times.
        """
        registry = get_default_registry()
        if registry.is_registered(cls.NAME):
            return

        def _factory(
            config: RuntimeConfig | None = None, **kwargs: object
        ) -> MockRuntime:
            del config, kwargs
            return cls()

        registry.register(
            cls.NAME,
            _factory,
            capabilities=RuntimeCapabilities(
                runtime_name=cls.NAME,
                tier="light",
                supports_mcp=False,
                supports_provider_override=False,
            ),
        )


def _remember_name(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.role != "user":
            continue
        lowered = message.content.lower()
        if "my name is" not in lowered:
            continue
        return message.content.split("My name is", 1)[-1].strip().rstrip(".")
    return None
