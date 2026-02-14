"""ClaudeSubagentOrchestrator — SDK-specific orchestration для subagent-ов."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator


class ClaudeSubagentOrchestrator(ThinSubagentOrchestrator):
    """SubagentOrchestrator с execution path через Claude RuntimeAdapter.

    Lifecycle (spawn/cancel/wait/status) берётся из ThinSubagentOrchestrator,
    а run(task) выполняется через SDK stream events.
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
    """Запуск subagent через RuntimeAdapter.stream_reply()."""

    def __init__(
        self,
        *,
        spec: SubagentSpec,
        adapter_factory: Callable[[SubagentSpec], Any],
    ) -> None:
        self._spec = spec
        self._adapter_factory = adapter_factory

    async def run(self, task: str) -> str:
        """Выполнить задачу через Claude SDK stream."""
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