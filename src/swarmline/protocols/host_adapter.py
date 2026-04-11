"""HostAdapter protocol — universal facade for spawning and managing AI agents.

Provides a simple spawn/send/stop API for external consumers (code_factory, CLI tools).
ISP: 4 methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from swarmline.multi_agent.graph_types import LifecycleMode


@dataclass(frozen=True)
class AgentAuthority:
    """Authority config passed at spawn time.

    Controls whether the spawned agent can create sub-agents and how deep.
    """

    can_spawn: bool = False
    max_children: int = 0
    max_depth: int = 1  # 1 = only direct children, no grandchildren
    can_delegate_authority: bool = False  # Can children also spawn?


@dataclass(frozen=True)
class AgentHandle:
    """Opaque handle returned by spawn_agent."""

    id: str
    role: str
    lifecycle: LifecycleMode = LifecycleMode.SUPERVISED
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentHandleStatus:
    """Status constants for agent handles."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@runtime_checkable
class HostAdapter(Protocol):
    """Universal API for spawning and managing AI agents. ISP: 4 methods.

    Implementations: AgentSDKAdapter (Claude), CodexAdapter (OpenAI/Codex).
    """

    async def spawn_agent(
        self,
        role: str,
        goal: str,
        *,
        system_prompt: str = "",
        model: str | None = None,
        tools: tuple[str, ...] = (),
        skills: tuple[str, ...] = (),
        hooks: tuple[str, ...] = (),
        lifecycle: LifecycleMode = LifecycleMode.SUPERVISED,
        authority: AgentAuthority | None = None,
        timeout: float | None = None,
    ) -> AgentHandle:
        """Spawn a new agent with the given role and goal."""
        ...  # pragma: no cover

    async def send_task(self, handle: AgentHandle, task: str) -> str:
        """Send a task to an existing agent. Returns response text."""
        ...  # pragma: no cover

    async def stop_agent(self, handle: AgentHandle) -> None:
        """Stop and clean up an agent."""
        ...  # pragma: no cover

    async def get_status(self, handle: AgentHandle) -> str:
        """Get the current status of an agent. Returns AgentHandleStatus constant."""
        ...  # pragma: no cover
