"""Shared test scaffolding for ``test_durable_runtime.py`` (Epic C Stage C1.1).

Extracted so the test module stays under the 400-line file-size cap (mirrors
the ``tests/unit/_graph_streaming_fakes.py`` / ``tests/unit/runtime/_followup_fakes.py``
convention for tests/ file-size discipline). Pure scaffolding — no
behavior/assertions live here, only fakes/helpers reused by ≥2 tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

from swarmline.domain_types import Message, RuntimeEvent, ToolSpec
from swarmline.durable import DurabilityConfig, DurabilityMode, DurableRuntime
from swarmline.session import InMemoryCheckpointer


class ScriptedRuntime:
    """Fake ``AgentRuntime`` yielding a pre-scripted event sequence.

    An item that is a ``BaseException`` instance is raised instead of
    yielded — simulates the inner runtime crashing mid-stream (no ``final``).
    """

    def __init__(self, events: list[RuntimeEvent | BaseException]) -> None:
        self._events = events
        self.cleanup_called = False
        self.cancel_called = False
        self.aenter_called = False
        self.aexit_called = False
        self.received_messages: list[Message] | None = None

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: Any = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        del system_prompt, active_tools, config, mode_hint
        self.received_messages = messages
        for item in self._events:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def cleanup(self) -> None:
        self.cleanup_called = True

    def cancel(self) -> None:
        self.cancel_called = True

    async def __aenter__(self) -> ScriptedRuntime:
        self.aenter_called = True
        return self

    async def __aexit__(self, *args: object) -> None:
        self.aexit_called = True


class RaisingOnRunningCheckpointer(InMemoryCheckpointer):
    """Checkpointer whose ``put`` always raises for progress (``running``)
    states — used to prove background-task failures are logged, never
    raised."""

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if state.get("status") == "running":
            raise RuntimeError("boom: checkpoint store unavailable")
        return await super().put(
            thread_id,
            state,
            resource_id=resource_id,
            parent_id=parent_id,
            checkpoint_id=checkpoint_id,
            metadata=metadata,
        )


class SlowRunningCheckpointer(InMemoryCheckpointer):
    """Persists a ``running`` state slowly -- simulates a slow/contended
    background checkpoint write racing against a fast terminal write."""

    def __init__(self, *, delay: float = 0.05) -> None:
        super().__init__()
        self._delay = delay

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if state.get("status") == "running":
            await asyncio.sleep(self._delay)
        return await super().put(
            thread_id,
            state,
            resource_id=resource_id,
            parent_id=parent_id,
            checkpoint_id=checkpoint_id,
            metadata=metadata,
        )


class FailsNthRunningCheckpointer(InMemoryCheckpointer):
    """Fails the Nth ``running``-state ``put`` (1-indexed); every other put
    succeeds. Proves a failed progress checkpoint is never referenced as the
    terminal checkpoint's ``parent_id`` (never a dangling reference)."""

    def __init__(self, *, fail_at: int = 2) -> None:
        super().__init__()
        self._fail_at = fail_at
        self._running_puts = 0

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if state.get("status") == "running":
            self._running_puts += 1
            if self._running_puts == self._fail_at:
                raise RuntimeError(f"boom: running checkpoint #{self._fail_at} failed")
        return await super().put(
            thread_id,
            state,
            resource_id=resource_id,
            parent_id=parent_id,
            checkpoint_id=checkpoint_id,
            metadata=metadata,
        )


def make_config(mode: DurabilityMode = "exit", **overrides: Any) -> DurabilityConfig:
    return DurabilityConfig(mode=mode, thread_id="t1", **overrides)


async def drain(runtime: DurableRuntime, **run_kwargs: Any) -> list[RuntimeEvent]:
    run_kwargs.setdefault("messages", [])
    run_kwargs.setdefault("system_prompt", "s")
    run_kwargs.setdefault("active_tools", [])
    return [event async for event in runtime.run(**run_kwargs)]
