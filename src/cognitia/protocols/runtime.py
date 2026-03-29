"""Runtime protocols -- AgentRuntime (v1) and RuntimePort (deprecated).

AgentRuntime is the canonical protocol for all runtime implementations.
Defined here in the protocols layer (Domain) with zero infrastructure dependencies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from cognitia.domain_types import Message, RuntimeEvent, ToolSpec

if TYPE_CHECKING:
    from cognitia.runtime.types import RuntimeConfig


class RuntimePort(Protocol):
    """Port: runtime adapter for SDK (DIP instead of concrete RuntimeAdapter).

    .. deprecated::
        Use :class:`AgentRuntime` for new code.
        RuntimePort is kept for backward compatibility with existing SessionManager.
    """

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def stream_reply(self, user_text: str) -> AsyncIterator[Any]: ...


@runtime_checkable
class AgentRuntime(Protocol):
    """Agent Runtime protocol — canonical interface for all runtimes.

    ISP: 4 methods (run, cleanup, cancel, context manager).
    """

    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run the agent loop, yielding streaming events."""
        ...  # pragma: no cover

    async def cleanup(self) -> None:
        """Release resources held by the runtime."""
        ...  # pragma: no cover

    def cancel(self) -> None:
        """Request cooperative cancellation of the current operation."""
        ...  # pragma: no cover

    async def __aenter__(self) -> AgentRuntime:
        """Async context manager entry."""
        ...  # pragma: no cover

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        ...  # pragma: no cover
