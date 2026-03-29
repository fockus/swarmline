"""Graph governance -- global limits and enforcement for the agent graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cognitia.multi_agent.graph_types import AgentCapabilities


@dataclass(frozen=True)
class GraphGovernanceConfig:
    """Global limits and defaults for the agent graph."""

    max_agents: int = 50
    max_depth: int = 5
    default_capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    allow_dynamic_hiring: bool = True
    allow_dynamic_delegation: bool = True


class GovernanceError(Exception):
    """Raised when a governance check fails."""

    def __init__(self, message: str, *, action: str = "", agent_id: str = "") -> None:
        super().__init__(message)
        self.action = action
        self.agent_id = agent_id


async def check_hire_allowed(
    config: GraphGovernanceConfig,
    parent_node: Any,  # AgentNode
    graph_query: Any,  # AgentGraphStore / AgentGraphQuery
) -> str | None:
    """Check if hiring a new agent is allowed.

    Returns error message string if denied, or None if allowed.
    """
    if not config.allow_dynamic_hiring:
        return "Dynamic hiring is globally disabled"

    caps: AgentCapabilities = parent_node.capabilities
    if not caps.can_hire:
        return f"Agent '{parent_node.name}' does not have can_hire permission"

    # Check max_children
    if caps.max_children is not None:
        children = await graph_query.get_children(parent_node.id)
        if len(children) >= caps.max_children:
            return (
                f"Agent '{parent_node.name}' has reached "
                f"max_children limit ({caps.max_children})"
            )

    # Check max_depth: chain includes self, so len(chain) is the depth
    chain = await graph_query.get_chain_of_command(parent_node.id)
    depth = len(chain)  # parent's depth (1-based)
    if depth >= config.max_depth:
        return f"Max graph depth ({config.max_depth}) would be exceeded"

    # Check max_agents via subtree from root
    root = await graph_query.get_root()
    if root is not None:
        subtree = await graph_query.get_subtree(root.id)
        if len(subtree) >= config.max_agents:
            return f"Max agents ({config.max_agents}) would be exceeded"

    return None


def check_delegate_allowed(
    config: GraphGovernanceConfig,
    agent_node: Any,  # AgentNode
) -> str | None:
    """Check if delegation is allowed.

    Returns error message string if denied, or None if allowed.
    """
    if not config.allow_dynamic_delegation:
        return "Dynamic delegation is globally disabled"

    if not agent_node.capabilities.can_delegate:
        return f"Agent '{agent_node.name}' does not have can_delegate permission"

    return None
