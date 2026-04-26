"""In-memory agent graph store — tree with traversal operations."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from typing import Any

from swarmline.multi_agent.graph_types import (
    AgentNode,
    EdgeType,
    GraphEdge,
    GraphSnapshot,
)


class InMemoryAgentGraph:
    """In-memory implementation of AgentGraphStore + AgentGraphQuery."""

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}
        self._lock = asyncio.Lock()

    # --- AgentGraphStore (5 methods) ---

    async def add_node(self, node: AgentNode) -> None:
        async with self._lock:
            if node.id in self._nodes:
                raise ValueError(f"Node '{node.id}' already exists")
            if node.parent_id is not None and node.parent_id not in self._nodes:
                raise ValueError(
                    f"Parent '{node.parent_id}' does not exist — "
                    f"add parent before child"
                )
            self._nodes[node.id] = node

    async def remove_node(self, node_id: str) -> bool:
        async with self._lock:
            if node_id not in self._nodes:
                return False
            # Cascade: collect all descendants
            to_remove = self._collect_subtree_ids(node_id)
            for nid in to_remove:
                del self._nodes[nid]
            return True

    async def get_node(self, node_id: str) -> AgentNode | None:
        return self._nodes.get(node_id)

    async def get_children(self, node_id: str) -> list[AgentNode]:
        return [n for n in self._nodes.values() if n.parent_id == node_id]

    async def update_node(self, node_id: str, **updates: Any) -> AgentNode | None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            # Validate parent_id change
            new_parent = updates.get("parent_id", node.parent_id)
            if new_parent != node.parent_id:
                if new_parent is not None and new_parent not in self._nodes:
                    raise ValueError(f"Parent '{new_parent}' does not exist")
                # Cycle check: new parent must not be in this node's subtree
                if new_parent is not None:
                    subtree_ids = {n for n in self._collect_subtree_ids(node_id)}
                    if new_parent in subtree_ids:
                        raise ValueError(
                            f"Cannot set parent to '{new_parent}' — would create a cycle"
                        )
            updated = replace(node, **updates)
            self._nodes[node_id] = updated
            return updated

    async def snapshot(self) -> GraphSnapshot:
        nodes = tuple(self._nodes.values())
        edges = tuple(
            GraphEdge(
                source_id=n.id, target_id=n.parent_id, edge_type=EdgeType.REPORTS_TO
            )
            for n in nodes
            if n.parent_id is not None
        )
        roots = [n for n in nodes if n.parent_id is None]
        root_id = roots[0].id if len(roots) == 1 else (roots[0].id if roots else None)
        return GraphSnapshot(nodes=nodes, edges=edges, root_id=root_id)

    # --- AgentGraphQuery (4 methods) ---

    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]:
        chain: list[AgentNode] = []
        visited: set[str] = set()
        current_id: str | None = node_id
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = self._nodes.get(current_id)
            if node is None:
                break
            chain.append(node)
            current_id = node.parent_id
        return chain

    async def get_subtree(self, node_id: str) -> list[AgentNode]:
        result: list[AgentNode] = []
        queue: deque[str] = deque([node_id])
        visited: set[str] = set()
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = self._nodes.get(nid)
            if node is None:
                continue
            result.append(node)
            for child in self._nodes.values():
                if child.parent_id == nid and child.id not in visited:
                    queue.append(child.id)
        return result

    async def get_root(self) -> AgentNode | None:
        for node in self._nodes.values():
            if node.parent_id is None:
                return node
        return None

    async def find_by_role(self, role: str) -> list[AgentNode]:
        return [n for n in self._nodes.values() if n.role == role]

    # --- Internal ---

    def _collect_subtree_ids(self, node_id: str) -> list[str]:
        """BFS to collect all descendant IDs including the starting node."""
        result: list[str] = []
        queue: deque[str] = deque([node_id])
        while queue:
            nid = queue.popleft()
            result.append(nid)
            for child in self._nodes.values():
                if child.parent_id == nid and child.id not in result:
                    queue.append(child.id)
        return result
