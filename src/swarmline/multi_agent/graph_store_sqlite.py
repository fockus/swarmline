"""SQLite-backed agent graph store with recursive CTE for traversal."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading

from dataclasses import replace
from typing import Any

from swarmline.multi_agent.graph_types import (
    AgentCapabilities,
    AgentNode,
    EdgeType,
    GraphEdge,
    GraphSnapshot,
    LifecycleMode,
)
from swarmline.multi_agent.registry_types import AgentStatus


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
            CREATE INDEX IF NOT EXISTS idx_an_parent ON agent_nodes(parent_id);
        """)
        self._conn.commit()

    # --- Serialization ---

    def _serialize(self, node: AgentNode) -> str:
        caps = node.capabilities
        return json.dumps(
            {
                "id": node.id,
                "name": node.name,
                "role": node.role,
                "system_prompt": node.system_prompt,
                "parent_id": node.parent_id,
                "allowed_tools": list(node.allowed_tools),
                "skills": list(node.skills),
                "mcp_servers": list(node.mcp_servers),
                "capabilities": {
                    "can_hire": caps.can_hire,
                    "can_delegate": caps.can_delegate,
                    "max_children": caps.max_children,
                    "max_depth": caps.max_depth,
                    "can_delegate_authority": caps.can_delegate_authority,
                    "can_use_subagents": caps.can_use_subagents,
                    "allowed_subagent_ids": list(caps.allowed_subagent_ids),
                    "can_use_team_mode": caps.can_use_team_mode,
                },
                "runtime_config": node.runtime_config,
                "model": node.model,
                "runtime": node.runtime,
                "api_key_env": node.api_key_env,
                "budget_limit_usd": node.budget_limit_usd,
                "lifecycle": node.lifecycle.value,
                "hooks": list(node.hooks),
                "status": node.status.value,
                "metadata": node.metadata,
            }
        )

    def _deserialize(self, data: str) -> AgentNode:
        d = json.loads(data)
        caps_data = d.get("capabilities", {})
        capabilities = (
            AgentCapabilities(
                can_hire=caps_data.get("can_hire", False),
                can_delegate=caps_data.get("can_delegate", True),
                max_children=caps_data.get("max_children"),
                max_depth=caps_data.get("max_depth"),
                can_delegate_authority=caps_data.get("can_delegate_authority", False),
                can_use_subagents=caps_data.get("can_use_subagents", False),
                allowed_subagent_ids=tuple(caps_data.get("allowed_subagent_ids", ())),
                can_use_team_mode=caps_data.get("can_use_team_mode", False),
            )
            if caps_data
            else AgentCapabilities()
        )
        lifecycle_str = d.get("lifecycle", "ephemeral")
        return AgentNode(
            id=d["id"],
            name=d["name"],
            role=d["role"],
            system_prompt=d.get("system_prompt", ""),
            parent_id=d.get("parent_id"),
            allowed_tools=tuple(d.get("allowed_tools", ())),
            skills=tuple(d.get("skills", ())),
            mcp_servers=tuple(d.get("mcp_servers", ())),
            capabilities=capabilities,
            runtime_config=d.get("runtime_config"),
            model=d.get("model", ""),
            runtime=d.get("runtime", ""),
            api_key_env=d.get("api_key_env"),
            budget_limit_usd=d.get("budget_limit_usd"),
            lifecycle=LifecycleMode(lifecycle_str),
            hooks=tuple(d.get("hooks", ())),
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
                cur2 = self._conn.execute(
                    "SELECT 1 FROM agent_nodes WHERE id=?", (node.parent_id,)
                )
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
            cur = self._conn.execute(
                "SELECT data FROM agent_nodes WHERE id=?", (node_id,)
            )
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
            GraphEdge(
                source_id=n.id, target_id=n.parent_id, edge_type=EdgeType.REPORTS_TO
            )
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
            cur = self._conn.execute(
                "SELECT data FROM agent_nodes WHERE json_extract(data, '$.role') = ?",
                (role,),
            )
            return [self._deserialize(r[0]) for r in cur.fetchall()]

    def _update_sync(self, node_id: str, **updates: Any) -> AgentNode | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM agent_nodes WHERE id=?", (node_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            node = self._deserialize(row[0])
            new_parent = updates.get("parent_id", node.parent_id)
            if new_parent != node.parent_id:
                if new_parent is not None:
                    p_cur = self._conn.execute(
                        "SELECT 1 FROM agent_nodes WHERE id=?", (new_parent,)
                    )
                    if not p_cur.fetchone():
                        raise ValueError(f"Parent '{new_parent}' does not exist")
                    subtree_ids = set(self._subtree_ids_sync(node_id))
                    if new_parent in subtree_ids:
                        raise ValueError(
                            f"Cannot set parent to '{new_parent}' — would create a cycle"
                        )
            updated = replace(node, **updates)
            self._conn.execute(
                "UPDATE agent_nodes SET parent_id = ?, data = ? WHERE id = ?",
                (updated.parent_id, self._serialize(updated), node_id),
            )
            self._conn.commit()
            return updated

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

    async def update_node(self, node_id: str, **updates: Any) -> AgentNode | None:
        return await asyncio.to_thread(self._update_sync, node_id, **updates)

    async def update_status(self, node_id: str, status: AgentStatus) -> None:
        await self.update_node(node_id, status=status)
