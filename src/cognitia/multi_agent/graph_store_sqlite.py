"""SQLite-backed agent graph store with recursive CTE for traversal."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading

from cognitia.multi_agent.graph_types import AgentNode, EdgeType, GraphEdge, GraphSnapshot
from cognitia.multi_agent.registry_types import AgentStatus


class SqliteAgentGraph:
    """SQLite implementation of AgentGraphStore + AgentGraphQuery."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_nodes (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                data TEXT NOT NULL,
                FOREIGN KEY(parent_id) REFERENCES agent_nodes(id)
            );
        """)
        self._conn.commit()

    # --- Serialization ---

    def _serialize(self, node: AgentNode) -> str:
        return json.dumps({
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
        })

    def _deserialize(self, data: str) -> AgentNode:
        d = json.loads(data)
        return AgentNode(
            id=d["id"],
            name=d["name"],
            role=d["role"],
            system_prompt=d.get("system_prompt", ""),
            parent_id=d.get("parent_id"),
            allowed_tools=tuple(d.get("allowed_tools", ())),
            skills=tuple(d.get("skills", ())),
            runtime_config=d.get("runtime_config"),
            budget_limit_usd=d.get("budget_limit_usd"),
            status=AgentStatus(d.get("status", "idle")),
            metadata=d.get("metadata", {}),
        )

    # --- Sync helpers ---

    def _add_sync(self, node: AgentNode) -> None:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM agent_nodes WHERE id=?", (node.id,))
            if cur.fetchone():
                raise ValueError(f"Node '{node.id}' already exists")
            if node.parent_id is not None:
                cur2 = self._conn.execute("SELECT 1 FROM agent_nodes WHERE id=?", (node.parent_id,))
                if not cur2.fetchone():
                    raise ValueError(
                        f"Parent '{node.parent_id}' does not exist — add parent before child"
                    )
            self._conn.execute(
                "INSERT INTO agent_nodes (id, parent_id, data) VALUES (?, ?, ?)",
                (node.id, node.parent_id, self._serialize(node)),
            )
            self._conn.commit()

    def _remove_sync(self, node_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM agent_nodes WHERE id=?", (node_id,))
            if not cur.fetchone():
                return False
            # Collect subtree via recursive CTE
            ids = self._subtree_ids_sync(node_id)
            placeholders = ",".join("?" * len(ids))
            self._conn.execute(
                f"DELETE FROM agent_nodes WHERE id IN ({placeholders})", ids
            )
            self._conn.commit()
            return True

    def _get_sync(self, node_id: str) -> AgentNode | None:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM agent_nodes WHERE id=?", (node_id,))
            row = cur.fetchone()
            return self._deserialize(row[0]) if row else None

    def _children_sync(self, node_id: str) -> list[AgentNode]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM agent_nodes WHERE parent_id=?", (node_id,)
            )
            return [self._deserialize(r[0]) for r in cur.fetchall()]

    def _snapshot_sync(self) -> GraphSnapshot:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM agent_nodes")
            nodes = tuple(self._deserialize(r[0]) for r in cur.fetchall())
        edges = tuple(
            GraphEdge(source_id=n.id, target_id=n.parent_id, edge_type=EdgeType.REPORTS_TO)
            for n in nodes
            if n.parent_id is not None
        )
        roots = [n for n in nodes if n.parent_id is None]
        root_id = roots[0].id if len(roots) == 1 else (roots[0].id if roots else None)
        return GraphSnapshot(nodes=nodes, edges=edges, root_id=root_id)

    def _chain_sync(self, node_id: str) -> list[AgentNode]:
        with self._lock:
            cur = self._conn.execute(
                """
                WITH RECURSIVE chain(id, parent_id, data) AS (
                    SELECT id, parent_id, data FROM agent_nodes WHERE id = ?
                    UNION ALL
                    SELECT n.id, n.parent_id, n.data
                    FROM agent_nodes n
                    JOIN chain c ON n.id = c.parent_id
                )
                SELECT data FROM chain
                """,
                (node_id,),
            )
            return [self._deserialize(r[0]) for r in cur.fetchall()]

    def _subtree_ids_sync(self, node_id: str) -> list[str]:
        cur = self._conn.execute(
            """
            WITH RECURSIVE sub(id) AS (
                SELECT id FROM agent_nodes WHERE id = ?
                UNION ALL
                SELECT n.id FROM agent_nodes n JOIN sub s ON n.parent_id = s.id
            )
            SELECT id FROM sub
            """,
            (node_id,),
        )
        return [r[0] for r in cur.fetchall()]

    def _subtree_sync(self, node_id: str) -> list[AgentNode]:
        with self._lock:
            cur = self._conn.execute(
                """
                WITH RECURSIVE sub(id, data) AS (
                    SELECT id, data FROM agent_nodes WHERE id = ?
                    UNION ALL
                    SELECT n.id, n.data FROM agent_nodes n JOIN sub s ON n.parent_id = s.id
                )
                SELECT data FROM sub
                """,
                (node_id,),
            )
            return [self._deserialize(r[0]) for r in cur.fetchall()]

    def _root_sync(self) -> AgentNode | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM agent_nodes WHERE parent_id IS NULL LIMIT 1"
            )
            row = cur.fetchone()
            return self._deserialize(row[0]) if row else None

    def _find_by_role_sync(self, role: str) -> list[AgentNode]:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM agent_nodes")
            nodes = [self._deserialize(r[0]) for r in cur.fetchall()]
        return [n for n in nodes if n.role == role]

    # --- AgentGraphStore (async) ---

    async def add_node(self, node: AgentNode) -> None:
        await asyncio.to_thread(self._add_sync, node)

    async def remove_node(self, node_id: str) -> bool:
        return await asyncio.to_thread(self._remove_sync, node_id)

    async def get_node(self, node_id: str) -> AgentNode | None:
        return await asyncio.to_thread(self._get_sync, node_id)

    async def get_children(self, node_id: str) -> list[AgentNode]:
        return await asyncio.to_thread(self._children_sync, node_id)

    async def snapshot(self) -> GraphSnapshot:
        return await asyncio.to_thread(self._snapshot_sync)

    # --- AgentGraphQuery (async) ---

    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]:
        return await asyncio.to_thread(self._chain_sync, node_id)

    async def get_subtree(self, node_id: str) -> list[AgentNode]:
        return await asyncio.to_thread(self._subtree_sync, node_id)

    async def get_root(self) -> AgentNode | None:
        return await asyncio.to_thread(self._root_sync)

    async def find_by_role(self, role: str) -> list[AgentNode]:
        return await asyncio.to_thread(self._find_by_role_sync, role)
