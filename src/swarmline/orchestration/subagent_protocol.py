"""Subagent Protocol module."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)


@runtime_checkable
class SubagentOrchestrator(Protocol):
    """Subagent Orchestrator protocol."""

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        """Run subagent. Returns agent_id."""
        ...

    async def get_status(self, agent_id: str) -> SubagentStatus:
        """Get status."""
        ...

    async def cancel(self, agent_id: str) -> None:
        """Cancel subagent."""
        ...

    async def wait(self, agent_id: str) -> SubagentResult:
        """Wait for the subagent to complete."""
        ...

    async def list_active(self) -> list[str]:
        """List active."""
        ...
