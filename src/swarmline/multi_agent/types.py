"""Domain types for multi-agent coordination.

All types are frozen dataclasses with zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentToolResult:
    """Result of executing an agent-as-tool call.

    Immutable value object capturing success/failure, output text,
    and usage metrics from a sub-agent invocation.
    """

    success: bool
    output: str
    error: str | None = None
    agent_id: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
