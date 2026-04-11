"""ExecutionContext — per-goal or per-unified-batch execution context.

Not to be confused with AgentExecutionContext (per-agent runtime context).
This context encapsulates namespace + board + budget partition + event scope for a goal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    """Execution isolation mode for goal contexts."""

    ISOLATED = "isolated"
    UNIFIED = "unified"


@dataclass(frozen=True)
class ExecutionContext:
    """Per-goal or per-unified-batch execution context.

    In isolated mode: 1 goal = 1 context with own namespace, board, budget.
    In unified mode: N goals = 1 context with shared boards and budget.
    """

    mode: ExecutionMode
    namespace: str
    namespaces: tuple[str, ...] = ()
    boards: dict[str, Any] = field(default_factory=dict)
    budget: Any | None = None
    event_bus: Any | None = None
    shared_agents: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create_isolated(
        cls,
        namespace: str,
        board: Any,
        budget_partition: Any | None = None,
        event_bus: Any | None = None,
    ) -> ExecutionContext:
        """Create an isolated context for a single goal."""
        return cls(
            mode=ExecutionMode.ISOLATED,
            namespace=namespace,
            namespaces=(namespace,),
            boards={namespace: board},
            budget=budget_partition,
            event_bus=event_bus,
        )

    @classmethod
    def create_unified(
        cls,
        namespaces: tuple[str, ...],
        boards: dict[str, Any],
        budget: Any | None = None,
        event_bus: Any | None = None,
        shared_agents: Any | None = None,
    ) -> ExecutionContext:
        """Create a unified context for multiple goals sharing resources."""
        return cls(
            mode=ExecutionMode.UNIFIED,
            namespace="",
            namespaces=namespaces,
            boards=boards,
            budget=budget,
            event_bus=event_bus,
            shared_agents=shared_agents,
        )

    @property
    def board(self) -> Any:
        """Primary board (isolated mode). Raises ValueError in unified mode."""
        if self.mode == ExecutionMode.UNIFIED:
            raise ValueError("Use get_board(namespace) in unified mode")
        return self.boards[self.namespace]

    def get_board(self, namespace: str) -> Any:
        """Get board by namespace. Works in both modes."""
        board = self.boards.get(namespace)
        if board is None:
            raise KeyError(f"No board for namespace: {namespace}")
        return board

    def scoped_event_type(self, event_type: str) -> str:
        """Prefix event_type with namespace in isolated mode, pass through in unified."""
        if self.mode == ExecutionMode.ISOLATED:
            return f"{self.namespace}:{event_type}"
        return event_type
