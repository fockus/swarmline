"""Shared fixtures for `CodeAgent` integration tests (code-agent-facade plan, Stage 2).

`FakeRuntimeFactory` implements `RuntimeFactoryPort` fully: capability/model
resolution is delegated to the real `RuntimeFactory` (so
`build_portable_runtime_plan`'s capability checks -- e.g. the
`thinking_stream` resolution -- behave exactly as in production), but
`.create()` returns a scripted `FakeCodeRuntime` instead of a real
`ThinRuntime`, so these tests stay fully offline (no LLM call).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from swarmline.domain_types import RuntimeEvent
from swarmline.runtime.types import RuntimeConfig


class FakeCodeRuntime:
    """Scripted fake `AgentRuntime` -- records its `run()` inputs, emits a
    fixed `RuntimeEvent` stream, and tracks whether `cleanup()` ran."""

    def __init__(
        self,
        events: list[RuntimeEvent],
        *,
        raise_after: BaseException | None = None,
        emit_gate: asyncio.Event | None = None,
    ) -> None:
        self._events = events
        #: When set, raised from the stream after the scripted events are
        #: exhausted -- simulates the underlying runtime failing mid-iteration
        #: so callers can assert `CodeAgent.run`'s `finally` still cleans up.
        self._raise_after = raise_after
        #: When set, awaited before EACH event -- lets a test suspend the
        #: facade inside `async for` (awaiting the next runtime event) and
        #: race `close()` against event delivery deterministically.
        self._emit_gate = emit_gate
        self.run_kwargs: dict[str, Any] | None = None
        #: Call COUNT (not a boolean) so tests can assert cleanup happens
        #: exactly once -- a boolean would hide double-cleanup bugs.
        self.cleanup_calls = 0

    def run(
        self,
        *,
        messages: list[Any],
        system_prompt: str,
        active_tools: list[Any],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        self.run_kwargs = {
            "messages": messages,
            "system_prompt": system_prompt,
            "active_tools": active_tools,
        }
        return self._stream()

    async def _stream(self) -> AsyncIterator[RuntimeEvent]:
        for event in self._events:
            if self._emit_gate is not None:
                await self._emit_gate.wait()
            yield event
        if self._raise_after is not None:
            raise self._raise_after

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


class FakeRuntimeFactory:
    """`RuntimeFactoryPort` test double for offline `CodeAgent` tests."""

    def __init__(
        self,
        events: list[RuntimeEvent] | None = None,
        *,
        raise_after: BaseException | None = None,
        emit_gate: asyncio.Event | None = None,
        runtime_cls: type[FakeCodeRuntime] = FakeCodeRuntime,
    ) -> None:
        from swarmline.runtime.factory import RuntimeFactory

        self._real = RuntimeFactory()
        self.events = (
            events
            if events is not None
            else [RuntimeEvent.assistant_delta("hi"), RuntimeEvent.final("hi")]
        )
        self._raise_after = raise_after
        self._emit_gate = emit_gate
        self._runtime_cls = runtime_cls
        self.created: list[FakeCodeRuntime] = []
        self.create_calls: list[dict[str, Any]] = []

    def validate_agent_config(self, config: Any) -> None:
        self._real.validate_agent_config(config)

    def resolve_agent_model(self, config: Any) -> str:
        return self._real.resolve_agent_model(config)

    def get_capabilities(
        self, config: Any = None, runtime_override: str | None = None
    ) -> Any:
        return self._real.get_capabilities(
            config=config, runtime_override=runtime_override
        )

    def validate_capabilities(
        self,
        config: Any = None,
        runtime_override: str | None = None,
        required_capabilities: Any = None,
    ) -> Any:
        return self._real.validate_capabilities(
            config=config,
            runtime_override=runtime_override,
            required_capabilities=required_capabilities,
        )

    def create(
        self,
        config: Any = None,
        runtime_override: str | None = None,
        **kwargs: Any,
    ) -> FakeCodeRuntime:
        self.create_calls.append(
            {"config": config, "runtime_override": runtime_override, **kwargs}
        )
        runtime = self._runtime_cls(
            list(self.events),
            raise_after=self._raise_after,
            emit_gate=self._emit_gate,
        )
        self.created.append(runtime)
        return runtime


@pytest.fixture
def fake_runtime_factory() -> FakeRuntimeFactory:
    """A fresh `FakeRuntimeFactory` per test."""
    return FakeRuntimeFactory()
