"""Base module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from cognitia.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)


@runtime_checkable
class AgentRuntime(Protocol):
    """Agent Runtime protocol."""

    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run."""
        ...  # pragma: no cover

    async def cleanup(self) -> None:
        """Cleanup."""
        ...  # pragma: no cover

    def cancel(self) -> None:
        """Request cooperative cancellation of the current operation."""
        ...  # pragma: no cover

    async def __aenter__(self) -> AgentRuntime:
        """Enter async context manager."""
        return self  # pragma: no cover

    async def __aexit__(self, *exc: Any) -> None:
        """Exit async context manager - calls cleanup()."""
        await self.cleanup()  # pragma: no cover
