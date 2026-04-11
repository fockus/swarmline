"""Procedural memory types — learned tool sequences as reusable procedures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProcedureStep:
    """A single step in a learned procedure."""

    tool_name: str
    args_template: dict[str, str] = field(default_factory=dict)
    expected_outcome: str = ""


@dataclass(frozen=True)
class Procedure:
    """A learned sequence of tool calls that achieved a goal."""

    id: str
    name: str
    description: str
    trigger: str  # when to suggest this procedure
    steps: tuple[ProcedureStep, ...] = ()
    success_count: int = 0
    failure_count: int = 0
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_uses(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        if self.total_uses == 0:
            return 0.0
        return self.success_count / self.total_uses


@runtime_checkable
class ProceduralMemory(Protocol):
    """Protocol for procedural memory — learned tool sequences."""

    async def store(self, procedure: Procedure) -> None:
        """Store a learned procedure."""
        ...

    async def suggest(self, query: str, *, top_k: int = 3) -> list[Procedure]:
        """Suggest procedures matching a task description."""
        ...

    async def record_outcome(self, proc_id: str, *, success: bool) -> None:
        """Record success/failure for a procedure (reinforcement)."""
        ...

    async def get(self, proc_id: str) -> Procedure | None:
        """Get a procedure by ID."""
        ...

    async def count(self) -> int:
        """Total number of stored procedures."""
        ...
