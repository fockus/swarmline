"""Agent graph domain types — nodes, edges, snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from swarmline.multi_agent.registry_types import AgentStatus


class LifecycleMode(str, Enum):
    """Agent lifecycle mode — how the agent lives and dies.

    EPHEMERAL: self-terminates after goal completion (default).
    SUPERVISED: creator decides when to terminate.
    PERSISTENT: only orchestrator/user can remove; stays alive across goals.
    """

    EPHEMERAL = "ephemeral"
    SUPERVISED = "supervised"
    PERSISTENT = "persistent"


class EdgeType(str, Enum):
    """Type of relationship between agent nodes."""

    REPORTS_TO = "reports_to"
    COLLABORATES = "collaborates"


@dataclass(frozen=True)
class AgentCapabilities:
    """Per-agent permission flags. Configurable when creating nodes."""

    # Graph governance -- can this agent modify the graph?
    can_hire: bool = False
    can_delegate: bool = True
    max_children: int | None = None  # None = unlimited
    max_depth: int | None = None  # Per-agent depth limit (None = use global)
    can_delegate_authority: bool = False  # Can children also hire sub-agents?

    # Runtime capabilities (outside graph)
    can_use_subagents: bool = False
    allowed_subagent_ids: tuple[str, ...] = ()  # () = all available
    can_use_team_mode: bool = False


@dataclass(frozen=True)
class AgentNode:
    """A node in the agent graph — an agent with identity, capabilities, and position."""

    id: str
    name: str
    role: str
    system_prompt: str = ""
    parent_id: str | None = None
    allowed_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    runtime_config: dict[str, Any] | None = None  # None = inherit from parent
    model: str = ""
    runtime: str = ""
    api_key_env: str | None = None
    budget_limit_usd: float | None = None
    lifecycle: LifecycleMode = LifecycleMode.SUPERVISED
    hooks: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.IDLE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """A directed edge between two agent nodes."""

    source_id: str
    target_id: str
    edge_type: EdgeType = EdgeType.REPORTS_TO


@dataclass(frozen=True)
class GraphSnapshot:
    """Immutable snapshot of the entire agent graph."""

    nodes: tuple[AgentNode, ...]
    edges: tuple[GraphEdge, ...]
    root_id: str | None = None
