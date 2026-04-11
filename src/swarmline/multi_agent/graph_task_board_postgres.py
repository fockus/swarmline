"""Postgres-backed graph task board — hierarchical tasks with atomic checkout."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.multi_agent.graph_task_board_shared import (
    deserialize_graph_task,
    deserialize_task_comment,
    serialize_graph_task,
    serialize_task_comment,
)
from swarmline.multi_agent.graph_task_types import GoalAncestry, GraphTaskItem, TaskComment
from swarmline.multi_agent.task_types import TaskStatus

POSTGRES_GRAPH_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_tasks (
    id TEXT PRIMARY KEY,
    parent_task_id TEXT REFERENCES graph_tasks(id),
    namespace TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_tasks_parent ON graph_tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_graph_tasks_namespace ON graph_tasks(namespace);

CREATE TABLE IF NOT EXISTS graph_task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES graph_tasks(id) ON DELETE CASCADE,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_graph_task_comments_task ON graph_task_comments(task_id);
"""


class PostgresGraphTaskBoard:
    """Postgres implementation of GraphTaskBoard + TaskCommentStore."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        namespace: str = "",
    ) -> None:
        self._sf = session_factory
        self._namespace = namespace

    @property
    def namespace(self) -> str:
        """Return the namespace this board operates on."""
        return self._namespace

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    # --- Serialization ---

    @staticmethod
    def _serialize_task(task: GraphTaskItem) -> dict[str, Any]:
        return serialize_graph_task(task)

    @staticmethod
    def _deserialize_task(data: dict[str, Any]) -> GraphTaskItem:
        return deserialize_graph_task(data)

    @staticmethod
    def _serialize_comment(comment: TaskComment) -> dict[str, Any]:
        return serialize_task_comment(comment)

    @staticmethod
    def _deserialize_comment(data: dict[str, Any]) -> TaskComment:
        return deserialize_task_comment(data)

    # --- GraphTaskBoard ---

    def _ns_where(self, base: str = "") -> str:
        """Append namespace filter when namespace is set."""
        if not self._namespace:
            return base
        conjunction = " AND " if base else " WHERE "
        return f"{base}{conjunction}namespace = :ns"

    def _ns_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge namespace param into existing params dict."""
        result = dict(params) if params else {}
        if self._namespace:
            result["ns"] = self._namespace
        return result

    async def create_task(self, task: GraphTaskItem) -> None:
        async with self._session(commit=True) as session:
            await self._validate_parent_link(session, task)
            await session.execute(
                text(
                    "INSERT INTO graph_tasks (id, parent_task_id, namespace, data) "
                    "VALUES (:id, :parent_task_id, :namespace, CAST(:data AS jsonb))"
                ),
                {"id": task.id, "parent_task_id": task.parent_task_id,
                 "namespace": self._namespace,
                 "data": json.dumps(self._serialize_task(task))},
            )

    async def _load_task_row(self, session: AsyncSession, task_id: str) -> GraphTaskItem | None:
        """Load a task row within the current namespace, if present."""
        where = self._ns_where("WHERE id = :id")
        row = (await session.execute(
            text(f"SELECT data FROM graph_tasks {where}"),
            self._ns_params({"id": task_id}),
        )).fetchone()
        if not row:
            return None
        return self._deserialize_task(row[0])

    async def _validate_parent_link(self, session: AsyncSession, task: GraphTaskItem) -> None:
        """Reject self-parenting and parent cycles before storing a task."""
        parent_id = task.parent_task_id
        if parent_id is None:
            return
        if parent_id == task.id:
            raise ValueError("Task cannot be its own parent")

        visited: set[str] = {task.id}
        current_id: str | None = parent_id
        while current_id is not None:
            if current_id in visited:
                raise ValueError("Cycle detected in parent_task_id chain")
            visited.add(current_id)
            current = await self._load_task_row(session, current_id)
            if current is None:
                return
            current_id = current.parent_task_id

    async def checkout_task(self, task_id: str, agent_id: str) -> GraphTaskItem | None:
        async with self._session(commit=True) as session:
            where = "WHERE id = :id AND (data->>'checkout_agent_id') IS NULL"
            where = self._ns_where(where)
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where} FOR UPDATE"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return None
            task = self._deserialize_task(row[0])
            updated = replace(
                task,
                status=TaskStatus.IN_PROGRESS,
                checkout_agent_id=agent_id,
                started_at=time.time(),
                updated_at=time.time(),
            )
            await session.execute(
                text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"id": task_id, "data": json.dumps(self._serialize_task(updated))},
            )
            return updated

    async def complete_task(self, task_id: str) -> bool:
        async with self._session(commit=True) as session:
            where = self._ns_where("WHERE id = :id")
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where} FOR UPDATE"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return False
            task = self._deserialize_task(row[0])
            if task.status != TaskStatus.IN_PROGRESS:
                return False
            updated = replace(
                task,
                status=TaskStatus.DONE,
                completed_at=time.time(),
                updated_at=time.time(),
                progress=1.0,
            )
            await session.execute(
                text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"id": task_id, "data": json.dumps(self._serialize_task(updated))},
            )
            # Propagate progress and completion to parent
            if task.parent_task_id:
                await self._propagate_parent(session, task.parent_task_id)
            return True

    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]:
        async with self._session() as session:
            where = self._ns_where("WHERE parent_task_id = :id")
            rows = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where}"),
                self._ns_params({"id": task_id}),
            )).fetchall()
            return [self._deserialize_task(r[0]) for r in rows]

    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]:
        async with self._session() as session:
            conditions: list[str] = []
            params: dict[str, Any] = {}
            if self._namespace:
                conditions.append("namespace = :ns")
                params["ns"] = self._namespace
            if "status" in filters:
                conditions.append("data->>'status' = :status")
                params["status"] = filters["status"].value if hasattr(filters["status"], "value") else str(filters["status"])
            if "assignee_agent_id" in filters:
                conditions.append("data->>'assignee_agent_id' = :assignee")
                params["assignee"] = filters["assignee_agent_id"]
            where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = (await session.execute(
                text(f"SELECT data FROM graph_tasks{where}"),  # noqa: S608
                params,
            )).fetchall()
            return [self._deserialize_task(r[0]) for r in rows]

    # --- Cancel (not part of core GraphTaskBoard protocol — ISP) ---

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Sets status to CANCELLED and releases checkout."""
        async with self._session(commit=True) as session:
            where = self._ns_where("WHERE id = :id")
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where} FOR UPDATE"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return False
            task = self._deserialize_task(row[0])
            if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                return False
            updated = replace(
                task,
                status=TaskStatus.CANCELLED,
                checkout_agent_id=None,
                completed_at=time.time(),
                updated_at=time.time(),
            )
            await session.execute(
                text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"id": task_id, "data": json.dumps(self._serialize_task(updated))},
            )
            return True

    # --- GraphTaskBlocker ---

    async def block_task(self, task_id: str, reason: str) -> bool:
        """Block a task with a mandatory reason."""
        if not reason or not reason.strip():
            return False
        async with self._session(commit=True) as session:
            where = self._ns_where("WHERE id = :id")
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where} FOR UPDATE"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return False
            task = self._deserialize_task(row[0])
            if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                return False
            updated = replace(
                task,
                status=TaskStatus.BLOCKED,
                blocked_reason=reason.strip(),
                checkout_agent_id=None,
                updated_at=time.time(),
            )
            await session.execute(
                text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"id": task_id, "data": json.dumps(self._serialize_task(updated))},
            )
            return True

    async def unblock_task(self, task_id: str) -> bool:
        """Unblock a task, returning it to TODO status."""
        async with self._session(commit=True) as session:
            where = self._ns_where("WHERE id = :id")
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where} FOR UPDATE"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return False
            task = self._deserialize_task(row[0])
            if task.status != TaskStatus.BLOCKED:
                return False
            updated = replace(
                task,
                status=TaskStatus.TODO,
                blocked_reason="",
                updated_at=time.time(),
            )
            await session.execute(
                text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"id": task_id, "data": json.dumps(self._serialize_task(updated))},
            )
            return True

    # --- GraphTaskScheduler ---

    async def get_ready_tasks(self) -> list[GraphTaskItem]:
        async with self._session() as session:
            base_where = "WHERE data->>'status' = 'todo' AND (data->>'checkout_agent_id') IS NULL"
            where = self._ns_where(base_where)
            rows = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where}"),
                self._ns_params(),
            )).fetchall()
            candidates = [self._deserialize_task(r[0]) for r in rows]
            if not candidates:
                return []
            # Load all tasks in namespace for dep resolution
            list_where = self._ns_where("")
            if list_where:
                all_rows = (await session.execute(
                    text(f"SELECT data FROM graph_tasks {list_where}"),
                    self._ns_params(),
                )).fetchall()
            else:
                all_rows = (await session.execute(
                    text("SELECT data FROM graph_tasks"),
                )).fetchall()
            statuses: dict[str, Any] = {}
            for r in all_rows:
                t = self._deserialize_task(r[0])
                statuses[t.id] = t.status
        ready: list[GraphTaskItem] = []
        for task in candidates:
            if not task.dependencies:
                ready.append(task)
                continue
            all_done = all(
                statuses.get(dep_id) == TaskStatus.DONE
                for dep_id in task.dependencies
            )
            if all_done:
                ready.append(task)
        return ready

    async def get_blocked_by(self, task_id: str) -> list[GraphTaskItem]:
        async with self._session() as session:
            where = self._ns_where("WHERE id = :id")
            row = (await session.execute(
                text(f"SELECT data FROM graph_tasks {where}"),
                self._ns_params({"id": task_id}),
            )).fetchone()
            if not row:
                return []
            task = self._deserialize_task(row[0])
            if not task.dependencies:
                return []
            if self._namespace:
                rows = (await session.execute(
                    text("SELECT data FROM graph_tasks WHERE id = ANY(:ids) AND namespace = :ns"),
                    {"ids": list(task.dependencies), "ns": self._namespace},
                )).fetchall()
            else:
                rows = (await session.execute(
                    text("SELECT data FROM graph_tasks WHERE id = ANY(:ids)"),
                    {"ids": list(task.dependencies)},
                )).fetchall()
            blockers: list[GraphTaskItem] = []
            for r in rows:
                t = self._deserialize_task(r[0])
                if t.status != TaskStatus.DONE:
                    blockers.append(t)
            return blockers

    # --- TaskCommentStore ---

    async def add_comment(self, comment: TaskComment) -> None:
        async with self._session(commit=True) as session:
            if await self._load_task_row(session, comment.task_id) is None:
                raise ValueError("Task not found in namespace")
            await session.execute(
                text(
                    "INSERT INTO graph_task_comments (id, task_id, data) "
                    "VALUES (:id, :task_id, CAST(:data AS jsonb))"
                ),
                {"id": comment.id, "task_id": comment.task_id,
                 "data": json.dumps(self._serialize_comment(comment))},
            )

    async def get_comments(self, task_id: str) -> list[TaskComment]:
        async with self._session() as session:
            if self._namespace:
                rows = (await session.execute(
                    text("""
                        SELECT c.data
                        FROM graph_task_comments c
                        JOIN graph_tasks t ON t.id = c.task_id
                        WHERE c.task_id = :id AND t.namespace = :ns
                        ORDER BY c.created_at
                    """),
                    {"id": task_id, "ns": self._namespace},
                )).fetchall()
            else:
                rows = (await session.execute(
                    text("SELECT data FROM graph_task_comments WHERE task_id = :id ORDER BY created_at"),
                    {"id": task_id},
                )).fetchall()
            return [self._deserialize_comment(r[0]) for r in rows]

    async def get_thread(self, task_id: str) -> list[TaskComment]:
        """Get all comments for a task and its subtasks (recursive)."""
        async with self._session() as session:
            if self._namespace:
                rows = (await session.execute(
                    text("""
                        WITH RECURSIVE sub(id) AS (
                            SELECT id FROM graph_tasks WHERE id = :id AND namespace = :ns
                            UNION ALL
                            SELECT t.id
                            FROM graph_tasks t
                            JOIN sub s ON t.parent_task_id = s.id
                            WHERE t.namespace = :ns
                        )
                        SELECT c.data FROM graph_task_comments c
                        WHERE c.task_id IN (SELECT id FROM sub)
                        ORDER BY c.created_at
                    """),
                    {"id": task_id, "ns": self._namespace},
                )).fetchall()
            else:
                rows = (await session.execute(
                    text("""
                        WITH RECURSIVE sub(id) AS (
                            SELECT id FROM graph_tasks WHERE id = :id
                            UNION ALL
                            SELECT t.id FROM graph_tasks t JOIN sub s ON t.parent_task_id = s.id
                        )
                        SELECT c.data FROM graph_task_comments c
                        WHERE c.task_id IN (SELECT id FROM sub)
                        ORDER BY c.created_at
                    """),
                    {"id": task_id},
                )).fetchall()
            return [self._deserialize_comment(r[0]) for r in rows]

    # --- GoalAncestry ---

    async def get_goal_ancestry(self, task_id: str) -> GoalAncestry | None:
        async with self._session() as session:
            if self._namespace:
                rows = (await session.execute(
                    text("""
                        WITH RECURSIVE ancestry(id, parent_task_id, data) AS (
                            SELECT id, parent_task_id, data
                            FROM graph_tasks
                            WHERE id = :id AND namespace = :ns
                            UNION ALL
                            SELECT t.id, t.parent_task_id, t.data
                            FROM graph_tasks t
                            JOIN ancestry a ON t.id = a.parent_task_id
                            WHERE t.namespace = :ns
                        )
                        SELECT data FROM ancestry
                    """),
                    {"id": task_id, "ns": self._namespace},
                )).fetchall()
            else:
                rows = (await session.execute(
                    text("""
                        WITH RECURSIVE ancestry(id, parent_task_id, data) AS (
                            SELECT id, parent_task_id, data FROM graph_tasks WHERE id = :id
                            UNION ALL
                            SELECT t.id, t.parent_task_id, t.data
                            FROM graph_tasks t JOIN ancestry a ON t.id = a.parent_task_id
                        )
                        SELECT data FROM ancestry
                    """),
                    {"id": task_id},
                )).fetchall()
        if not rows:
            return None
        tasks = [self._deserialize_task(r[0]) for r in rows]
        root = tasks[-1]
        goal_id = root.goal_id
        if not goal_id:
            return None
        chain = tuple(t.id for t in reversed(tasks))
        return GoalAncestry(root_goal_id=goal_id, chain=chain)

    # --- Internal ---

    async def _propagate_parent(self, session: AsyncSession, parent_id: str) -> None:
        """Recalculate parent progress from children and auto-complete if all DONE.

        Always recurses to grandparent since progress changes even with partial completion.
        """
        # Lock all children to prevent concurrent propagation race
        if self._namespace:
            rows = (await session.execute(
                text("""
                    SELECT data FROM graph_tasks
                    WHERE parent_task_id = :id AND namespace = :ns
                    FOR UPDATE
                """),
                {"id": parent_id, "ns": self._namespace},
            )).fetchall()
        else:
            rows = (await session.execute(
                text("SELECT data FROM graph_tasks WHERE parent_task_id = :id FOR UPDATE"),
                {"id": parent_id},
            )).fetchall()
        if not rows:
            return
        children = [self._deserialize_task(r[0]) for r in rows]
        progress = sum(c.progress for c in children) / len(children)
        if self._namespace:
            parent_row = (await session.execute(
                text("""
                    SELECT data FROM graph_tasks
                    WHERE id = :id AND namespace = :ns
                    FOR UPDATE
                """),
                {"id": parent_id, "ns": self._namespace},
            )).fetchone()
        else:
            parent_row = (await session.execute(
                text("SELECT data FROM graph_tasks WHERE id = :id FOR UPDATE"),
                {"id": parent_id},
            )).fetchone()
        if not parent_row:
            return
        parent = self._deserialize_task(parent_row[0])
        if all(c.status == TaskStatus.DONE for c in children):
            updated = replace(
                parent,
                status=TaskStatus.DONE,
                completed_at=time.time(),
                updated_at=time.time(),
                progress=progress,
            )
        else:
            updated = replace(parent, progress=progress, updated_at=time.time())
        await session.execute(
            text("UPDATE graph_tasks SET data = CAST(:data AS jsonb) WHERE id = :id"),
            {"id": parent_id, "data": json.dumps(self._serialize_task(updated))},
        )
        # Always recurse — progress changes even with partial completion
        if parent.parent_task_id:
            await self._propagate_parent(session, parent.parent_task_id)
