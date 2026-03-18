"""Subagent Types module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from cognitia.runtime.types import Message, ToolSpec, TurnMetrics
from cognitia.tools.types import SandboxConfig

SubagentState = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class SubagentSpec:
    """Spetsandfandtoatsandya subagent'a - what run."""

    name: str
    system_prompt: str
    tools: list[ToolSpec] = field(default_factory=list)
    sandbox_config: SandboxConfig | None = None


@dataclass(frozen=True)
class SubagentStatus:
    """Tetoushandy status subagent'a."""

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
