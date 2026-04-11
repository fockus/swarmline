"""Agent execution context — structured data for the runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentExecutionContext:
    """Full context for executing an agent in the graph orchestrator.

    Replaces the old (agent_id, task_id, goal, system_prompt) tuple
    with a structured object that includes tools, skills, MCP servers,
    and runtime configuration.
    """

    agent_id: str
    task_id: str
    goal: str
    system_prompt: str
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    runtime_config: dict[str, Any] | None = None
    budget_limit_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
