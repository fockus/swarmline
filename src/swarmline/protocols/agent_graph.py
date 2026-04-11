"""Agent graph protocols — store and query operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.multi_agent.graph_types import AgentNode, GraphSnapshot


@runtime_checkable
class AgentGraphStore(Protocol):
    """Mutation operations on the agent graph. ISP: 5 methods."""

    async def add_node(self, node: AgentNode) -> None: ...
    async def remove_node(self, node_id: str) -> bool: ...
    async def get_node(self, node_id: str) -> AgentNode | None: ...
    async def get_children(self, node_id: str) -> list[AgentNode]: ...
    async def snapshot(self) -> GraphSnapshot: ...


@runtime_checkable
class AgentGraphQuery(Protocol):
    """Read-only traversal of the agent graph. ISP: 4 methods."""

    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]: ...
    async def get_subtree(self, node_id: str) -> list[AgentNode]: ...
    async def get_root(self) -> AgentNode | None: ...
    async def find_by_role(self, role: str) -> list[AgentNode]: ...


@runtime_checkable
class AgentNodeUpdater(Protocol):
    """Partial update of agent nodes without remove+add. ISP: 1 method."""

    async def update_node(self, node_id: str, **updates: Any) -> AgentNode | None: ...
