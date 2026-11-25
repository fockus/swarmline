"""Subagent Types module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from swarmline.runtime.types import Message, ToolSpec, TurnMetrics
from swarmline.tools.types import SandboxConfig

if TYPE_CHECKING:
    from swarmline.orchestration.context_bridge import ContextBridge

SubagentState = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class SubagentSpec:
    """Specification for a subagent — defines what to run."""

    name: str
    system_prompt: str
    tools: list[ToolSpec] = field(default_factory=list)
    sandbox_config: SandboxConfig | None = None
    isolation: str | None = None
    run_in_background: bool = False
    context_bridge: ContextBridge | None = None
    runtime_name: str | None = None  # REQ-RCA-050: named runtime via RuntimeRegistry
    # REQ-ORC-043: this child's own recursion depth (parent's current_depth + 1).
    depth: int = 0

    def __post_init__(self) -> None:
        """Fail fast on a negative depth (fix-cycle 2, MINOR-3): a hand-built
        or malicious `SubagentSpec(depth=-1)` would silently reset/bypass the
        depth-guard in `create_subagent_executor` (`current_depth >= max_depth`
        never trips for a negative starting point)."""
        if self.depth < 0:
            raise ValueError(f"SubagentSpec.depth must be >= 0, got {self.depth}")


@dataclass(frozen=True)
class SubagentStatus:
    """Current status of a running or completed sub-agent."""

    state: SubagentState = "pending"
    progress: str = ""
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class SubagentResult:
    """Result of the subagent's work."""

    agent_id: str
    status: SubagentStatus
    output: str
    messages: list[Message] = field(default_factory=list)
    metrics: TurnMetrics | None = None
