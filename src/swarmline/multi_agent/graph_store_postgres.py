"""Postgres-backed agent graph store — recursive CTE for traversal.

Uses SQLAlchemy async + asyncpg. Same constructor pattern as PostgresMemoryProvider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.multi_agent.graph_types import AgentNode, EdgeType, GraphEdge, GraphSnapshot
from swarmline.multi_agent.registry_types import AgentStatus

POSTGRES_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES agent_nodes(id) ON DELETE CASCADE,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_nodes_parent ON agent_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_agent_nodes_role ON agent_nodes((data->>'role'));
"""


class PostgresAgentGraph:
    """Postgres implementation of AgentGraphStore + AgentGraphQuery.

    Uses recursive CTEs for chain-of-command and subtree traversal.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    # --- Serialization ---

    @staticmethod
    def _serialize(node: AgentNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "role": node.role,
            "system_prompt": node.system_prompt,
            "parent_id": node.parent_id,
            "allowed_tools": list(node.allowed_tools),
            "skills": list(node.skills),
            "runtime_config": node.runtime_config,
            "budget_limit_usd": node.budget_limit_usd,
            "status": node.status.value,
            "metadata": node.metadata,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> AgentNode:
        return AgentNode(
            id=data["id"],
            name=data["name"],
            role=data["role"],
            system_prompt=data.get("system_prompt", ""),
            parent_id=data.get("parent_id"),
            allowed_tools=tuple(data.get("allowed_tools", ())),
            skills=tuple(data.get("skills", ())),
            runtime_config=data.get("runtime_config"),
            budget_limit_usd=data.get("budget_limit_usd"),
            status=AgentStatus(data.get("status", "idle")),
            metadata=data.get("metadata", {}),
        )

    # --- AgentGraphStore ---

    async def add_node(self, node: AgentNode) -> None:
        async with self._session(commit=True) as session:
            # Check duplicates
            row = (await session.execute(
                text("SELECT 1 FROM agent_nodes WHERE id = :id"), {"id": node.id},
            )).fetchone()
            if row:
                raise ValueError(f"Node '{node.id}' already exists")
            # Check parent exists
            if node.parent_id is not None:
                parent_row = (await session.execute(
                    text("SELECT 1 FROM agent_nodes WHERE id = :id"), {"id": node.parent_id},
                )).fetchone()
                if not parent_row:
                    raise ValueError(
                        f"Parent '{node.parent_id}' does not exist — add parent before child"
                    )
            await session.execute(
                text(
                    "INSERT INTO agent_nodes (id, parent_id, data) "
                    "VALUES (:id, :parent_id, CAST(:data AS jsonb))"
                ),
                {"id": node.id, "parent_id": node.parent_id,
                 "data": json.dumps(self._serialize(node))},
            )

    async def remove_node(self, node_id: str) -> bool:
        async with self._session(commit=True) as session:
            row = (await session.execute(
                text("SELECT 1 FROM agent_nodes WHERE id = :id"), {"id": node_id},
            )).fetchone()
            if not row:
                return False
            # CASCADE handles children, but we do explicit subtree delete for consistency
            ids = await self._subtree_ids(session, node_id)
            await session.execute(
                text("DELETE FROM agent_nodes WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            return True

    async def get_node(self, node_id: str) -> AgentNode | None:
        async with self._session() as session:
            row = (await session.execute(
                text("SELECT data FROM agent_nodes WHERE id = :id"), {"id": node_id},
            )).fetchone()
            return self._deserialize(row[0]) if row else None

    async def get_children(self, node_id: str) -> list[AgentNode]:
        async with self._session() as session:
            rows = (await session.execute(
                text("SELECT data FROM agent_nodes WHERE parent_id = :id"),
                {"id": node_id},
            )).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def snapshot(self) -> GraphSnapshot:
        async with self._session() as session:
            rows = (await session.execute(text("SELECT data FROM agent_nodes"))).fetchall()
            nodes = tuple(self._deserialize(r[0]) for r in rows)
        edges = tuple(
            GraphEdge(source_id=n.id, target_id=n.parent_id, edge_type=EdgeType.REPORTS_TO)
            for n in nodes if n.parent_id is not None
        )
        roots = [n for n in nodes if n.parent_id is None]
        root_id = roots[0].id if len(roots) == 1 else (roots[0].id if roots else None)
        return GraphSnapshot(nodes=nodes, edges=edges, root_id=root_id)

    # --- AgentNodeUpdater ---

    async def update_node(self, node_id: str, **updates: Any) -> AgentNode | None:
        async with self._session(commit=True) as session:
            row = (await session.execute(
                text("SELECT data FROM agent_nodes WHERE id = :id FOR UPDATE"),
                {"id": node_id},
            )).fetchone()
            if not row:
                return None
            node = self._deserialize(row[0])
            new_parent = updates.get("parent_id", node.parent_id)
            if new_parent != node.parent_id:
                if new_parent is not None:
                    parent_row = (await session.execute(
                        text("SELECT 1 FROM agent_nodes WHERE id = :id"),
                        {"id": new_parent},
                    )).fetchone()
                    if not parent_row:
                        raise ValueError(f"Parent '{new_parent}' does not exist")
                    subtree_ids = set(await self._subtree_ids(session, node_id))
                    if new_parent in subtree_ids:
                        raise ValueError(
                            f"Cannot set parent to '{new_parent}' — would create a cycle"
                        )
            from dataclasses import replace
            updated = replace(node, **updates)
            await session.execute(
                text(
                    "UPDATE agent_nodes SET parent_id = :parent_id, "
                    "data = CAST(:data AS jsonb) WHERE id = :id"
                ),
                {"id": node_id, "parent_id": updated.parent_id,
                 "data": json.dumps(self._serialize(updated))},
            )
            return updated

    # --- AgentGraphQuery ---

    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]:
        async with self._session() as session:
            rows = (await session.execute(
                text("""
                    WITH RECURSIVE chain(id, parent_id, data) AS (
                        SELECT id, parent_id, data FROM agent_nodes WHERE id = :id
                        UNION ALL
                        SELECT n.id, n.parent_id, n.data
                        FROM agent_nodes n JOIN chain c ON n.id = c.parent_id
                    )
                    SELECT data FROM chain
                """),
                {"id": node_id},
            )).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def get_subtree(self, node_id: str) -> list[AgentNode]:
        async with self._session() as session:
            rows = (await session.execute(
                text("""
                    WITH RECURSIVE sub(id, data) AS (
                        SELECT id, data FROM agent_nodes WHERE id = :id
                        UNION ALL
                        SELECT n.id, n.data
                        FROM agent_nodes n JOIN sub s ON n.parent_id = s.id
                    )
                    SELECT data FROM sub
                """),
                {"id": node_id},
            )).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def get_root(self) -> AgentNode | None:
        async with self._session() as session:
            row = (await session.execute(
                text("SELECT data FROM agent_nodes WHERE parent_id IS NULL LIMIT 1"),
            )).fetchone()
            return self._deserialize(row[0]) if row else None

    async def find_by_role(self, role: str) -> list[AgentNode]:
        async with self._session() as session:
            rows = (await session.execute(
                text("SELECT data FROM agent_nodes WHERE data->>'role' = :role"),
                {"role": role},
            )).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    # --- Internal helpers ---

    @staticmethod
    async def _subtree_ids(session: AsyncSession, node_id: str) -> list[str]:
        rows = (await session.execute(
            text("""
                WITH RECURSIVE sub(id) AS (
                    SELECT id FROM agent_nodes WHERE id = :id
                    UNION ALL
                    SELECT n.id FROM agent_nodes n JOIN sub s ON n.parent_id = s.id
                )
                SELECT id FROM sub
            """),
            {"id": node_id},
        )).fetchall()
        return [r[0] for r in rows]
