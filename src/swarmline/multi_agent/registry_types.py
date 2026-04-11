"""Domain types for agent registry (Phase 9C-MVP).

All types are frozen dataclasses with zero external dependencies.
AgentStatus is a str Enum for JSON-friendly serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    """Lifecycle status of a registered agent."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True)
class AgentRecord:
    """Immutable record describing a registered agent.

    Fields:
        id: Unique agent identifier.
        name: Human-readable agent name.
        role: Agent's role (e.g. "researcher", "coder", "reviewer").
        parent_id: ID of the parent agent (None for top-level).
        runtime_name: Name of the runtime to use (default: "thin").
        runtime_config: Runtime-specific configuration.
        status: Current lifecycle status.
        budget_limit_usd: Optional spending cap in USD.
        metadata: Arbitrary key-value metadata.
    """

    id: str
    name: str
    role: str
    parent_id: str | None = None
    runtime_name: str = "thin"
    runtime_config: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.IDLE
    budget_limit_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentFilter:
    """Filter criteria for querying registered agents.

    All fields are optional; None means "no filter on this field".
    """

    role: str | None = None
    status: AgentStatus | None = None
    parent_id: str | None = None
