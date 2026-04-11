"""ClaudeSubagentOrchestrator — SDK-specific orchestration for subagents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator


class ClaudeSubagentOrchestrator(ThinSubagentOrchestrator):
    """SubagentOrchestrator with execution path via Claude RuntimeAdapter.

    Lifecycle (spawn/cancel/wait/status) is taken from ThinSubagentOrchestrator,
    and run(task) is performed via SDK stream events.
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        *,
        adapter_factory: Callable[[SubagentSpec], Any] | None = None,
    ) -> None:
        super().__init__(max_concurrent=max_concurrent)
        self._adapter_factory = adapter_factory

    def _create_runtime(self, spec: SubagentSpec) -> _ClaudeWorkerRuntime:
        if self._adapter_factory is None:
            raise RuntimeError(
                "ClaudeSubagentOrchestrator требует adapter_factory (RuntimeAdapter per worker).",
            )
        return _ClaudeWorkerRuntime(spec=spec, adapter_factory=self._adapter_factory)


class _ClaudeWorkerRuntime:
    """Run subagent via RuntimeAdapter.stream_reply()."""

    def __init__(
        self,
        *,
        spec: SubagentSpec,
        adapter_factory: Callable[[SubagentSpec], Any],
    ) -> None:
        self._spec = spec
        self._adapter_factory = adapter_factory

    async def run(self, task: str) -> str:
        """Complete the task via the Claude SDK stream."""
        adapter = self._adapter_factory(self._spec)
        if hasattr(adapter, "connect"):
            await adapter.connect()

        full_text = ""
        try:
            async for event in adapter.stream_reply(task):
                etype = getattr(event, "type", "")
                if etype == "text_delta":
                    full_text += str(getattr(event, "text", ""))
                elif etype == "error":
                    message = str(getattr(event, "text", "Claude subagent error"))
                    raise RuntimeError(message)
        finally:
            if hasattr(adapter, "disconnect") and getattr(adapter, "is_connected", False):
                await adapter.disconnect()

        return full_text
