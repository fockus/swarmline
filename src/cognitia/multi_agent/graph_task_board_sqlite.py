"""SQLite-backed graph task board — hierarchical tasks with atomic checkout."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from dataclasses import replace
from typing import Any

from cognitia.multi_agent.graph_task_types import GoalAncestry, GraphTaskItem, TaskComment
from cognitia.multi_agent.task_types import TaskPriority, TaskStatus

_DDL = """
CREATE TABLE IF NOT EXISTS graph_tasks (
    id TEXT PRIMARY KEY,
    parent_task_id TEXT,
    namespace TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL,
    FOREIGN KEY(parent_task_id) REFERENCES graph_tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_gt_parent ON graph_tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_gt_namespace ON graph_tasks(namespace);

CREATE TABLE IF NOT EXISTS graph_task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(task_id) REFERENCES graph_tasks(id)
);
"""

_MIGRATE_NAMESPACE = (
    "ALTER TABLE graph_tasks ADD COLUMN namespace TEXT NOT NULL DEFAULT ''",
)



class SqliteGraphTaskBoard:
    """SQLite implementation of GraphTaskBoard + TaskCommentStore.

    Uses asyncio.to_thread for non-blocking I/O.
    """

    def __init__(self, db_path: str = ":memory:", namespace: str = "") -> None:
        self._namespace = namespace
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.executescript(_DDL)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Apply forward-compatible migrations for namespace column."""
        for stmt in _MIGRATE_NAMESPACE:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

    @property
    def namespace(self) -> str:
        """Return the namespace this board operates on."""
        return self._namespace

    # --- Serialization ---

    @staticmethod
    def _ser(task: GraphTaskItem) -> str:
        return json.dumps({
            "id": task.id, "title": task.title, "description": task.description,
            "status": task.status.value, "priority": task.priority.value,
            "assignee_agent_id": task.assignee_agent_id,
            "parent_task_id": task.parent_task_id,
            "goal_id": task.goal_id, "epic_id": task.epic_id,
            "dod_criteria": list(task.dod_criteria),
            "dod_verified": task.dod_verified,
            "checkout_agent_id": task.checkout_agent_id,
            "dependencies": list(task.dependencies),
            "delegated_by": task.delegated_by,
            "delegation_reason": task.delegation_reason,
            "estimated_effort": task.estimated_effort,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "progress": task.progress,
            "stage": task.stage,
            "blocked_reason": task.blocked_reason,
            "created_at": task.created_at, "updated_at": task.updated_at,
            "metadata": task.metadata,
        })

    @staticmethod
    def _deser(raw: str) -> GraphTaskItem:
        d = json.loads(raw)
        return GraphTaskItem(
            id=d["id"], title=d["title"], description=d.get("description", ""),
            status=TaskStatus(d.get("status", "todo")),
            priority=TaskPriority(d.get("priority", "medium")),
            assignee_agent_id=d.get("assignee_agent_id"),
            parent_task_id=d.get("parent_task_id"),
            goal_id=d.get("goal_id"),
            epic_id=d.get("epic_id"),
            dod_criteria=tuple(d.get("dod_criteria", ())),
            dod_verified=d.get("dod_verified", False),
            checkout_agent_id=d.get("checkout_agent_id"),
            dependencies=tuple(d.get("dependencies", ())),
            delegated_by=d.get("delegated_by"),
            delegation_reason=d.get("delegation_reason"),
            estimated_effort=d.get("estimated_effort"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            progress=d.get("progress", 0.0),
            stage=d.get("stage", ""),
            blocked_reason=d.get("blocked_reason", ""),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            metadata=d.get("metadata", {}),
        )

    # --- Sync helpers ---

    def _create_sync(self, task: GraphTaskItem) -> None:
        with self._lock:
            self._validate_parent_link_sync(task)
            self._conn.execute(
                "INSERT INTO graph_tasks (id, parent_task_id, namespace, data) VALUES (?, ?, ?, ?)",
                (task.id, task.parent_task_id, self._namespace, self._ser(task)),
            )
            self._conn.commit()

    def _load_task_sync(self, task_id: str) -> GraphTaskItem | None:
        params: list[Any] = [task_id]
        query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
        cur = self._conn.execute(query, params)
        row = cur.fetchone()
        if not row:
            return None
        return self._deser(row[0])

    def _validate_parent_link_sync(self, task: GraphTaskItem) -> None:
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
            current = self._load_task_sync(current_id)
            if current is None:
                return
            current_id = current.parent_task_id

    def _ns_filter(self, base_query: str, params: list[Any]) -> str:
        """Append namespace filter to query when namespace is set."""
        if self._namespace:
            params.append(self._namespace)
            return f"{base_query} AND namespace = ?"
        return base_query

    def _checkout_sync(self, task_id: str, agent_id: str) -> GraphTaskItem | None:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                params: list[Any] = [task_id]
                query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
                cur = self._conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    self._conn.commit()
                    return None
                task = self._deser(row[0])
                if task.checkout_agent_id is not None:
                    self._conn.commit()
                    return None
                updated = replace(
                    task,
                    status=TaskStatus.IN_PROGRESS,
                    checkout_agent_id=agent_id,
                    started_at=time.time(),
                    updated_at=time.time(),
                )
                self._conn.execute(
                    "UPDATE graph_tasks SET data = ? WHERE id = ?",
                    (self._ser(updated), task_id),
                )
                self._conn.commit()
                return updated
            except Exception:
                self._conn.rollback()
                raise

    def _complete_sync(self, task_id: str) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                params: list[Any] = [task_id]
                query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
                cur = self._conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    self._conn.commit()
                    return False
                task = self._deser(row[0])
                if task.status != TaskStatus.IN_PROGRESS:
                    self._conn.commit()
                    return False
                updated = replace(
                    task,
                    status=TaskStatus.DONE,
                    completed_at=time.time(),
                    updated_at=time.time(),
                    progress=1.0,
                )
                self._conn.execute(
                    "UPDATE graph_tasks SET data = ? WHERE id = ?",
                    (self._ser(updated), task_id),
                )
                # Propagate progress and completion within the same transaction
                if task.parent_task_id:
                    self._propagate_parent_sync(task.parent_task_id)
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def _block_sync(self, task_id: str, reason: str) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                params: list[Any] = [task_id]
                query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
                cur = self._conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    self._conn.commit()
                    return False
                if not reason or not reason.strip():
                    self._conn.commit()
                    return False
                task = self._deser(row[0])
                if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                    self._conn.commit()
                    return False
                updated = replace(
                    task,
                    status=TaskStatus.BLOCKED,
                    blocked_reason=reason.strip(),
                    checkout_agent_id=None,
                    updated_at=time.time(),
                )
                self._conn.execute(
                    "UPDATE graph_tasks SET data = ? WHERE id = ?",
                    (self._ser(updated), task_id),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def _unblock_sync(self, task_id: str) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                params: list[Any] = [task_id]
                query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
                cur = self._conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    self._conn.commit()
                    return False
                task = self._deser(row[0])
                if task.status != TaskStatus.BLOCKED:
                    self._conn.commit()
                    return False
                updated = replace(
                    task,
                    status=TaskStatus.TODO,
                    blocked_reason="",
                    updated_at=time.time(),
                )
                self._conn.execute(
                    "UPDATE graph_tasks SET data = ? WHERE id = ?",
                    (self._ser(updated), task_id),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def _cancel_sync(self, task_id: str) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                params: list[Any] = [task_id]
                query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
                cur = self._conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    self._conn.commit()
                    return False
                task = self._deser(row[0])
                if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                    self._conn.commit()
                    return False
                updated = replace(
                    task,
                    status=TaskStatus.CANCELLED,
                    checkout_agent_id=None,
                    completed_at=time.time(),
                    updated_at=time.time(),
                )
                self._conn.execute(
                    "UPDATE graph_tasks SET data = ? WHERE id = ?",
                    (self._ser(updated), task_id),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def _propagate_parent_sync(self, parent_id: str) -> None:
        """Recalculate parent progress from children and auto-complete if all DONE.

        Must be called within an active transaction. Always recurses to grandparent.
        """
        params: list[Any] = [parent_id]
        query = self._ns_filter("SELECT data FROM graph_tasks WHERE parent_task_id = ?", params)
        cur = self._conn.execute(query, params)
        children = [self._deser(r[0]) for r in cur.fetchall()]
        if not children:
            return
        progress = sum(c.progress for c in children) / len(children)
        params2: list[Any] = [parent_id]
        query2 = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params2)
        cur2 = self._conn.execute(query2, params2)
        row = cur2.fetchone()
        if not row:
            return
        parent = self._deser(row[0])
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
        self._conn.execute(
            "UPDATE graph_tasks SET data = ? WHERE id = ?",
            (self._ser(updated), parent_id),
        )
        # Always recurse — progress changes even with partial completion
        if parent.parent_task_id:
            self._propagate_parent_sync(parent.parent_task_id)

    def _subtasks_sync(self, task_id: str) -> list[GraphTaskItem]:
        with self._lock:
            params: list[Any] = [task_id]
            query = self._ns_filter("SELECT data FROM graph_tasks WHERE parent_task_id = ?", params)
            cur = self._conn.execute(query, params)
            return [self._deser(r[0]) for r in cur.fetchall()]

    def _list_sync(self) -> list[GraphTaskItem]:
        with self._lock:
            if self._namespace:
                cur = self._conn.execute(
                    "SELECT data FROM graph_tasks WHERE namespace = ?", (self._namespace,),
                )
            else:
                cur = self._conn.execute("SELECT data FROM graph_tasks")
            return [self._deser(r[0]) for r in cur.fetchall()]

    def _add_comment_sync(self, comment: TaskComment) -> None:
        with self._lock:
            if self._load_task_sync(comment.task_id) is None:
                raise ValueError("Task not found in namespace")
            data = json.dumps({
                "id": comment.id, "task_id": comment.task_id,
                "author_agent_id": comment.author_agent_id,
                "content": comment.content, "created_at": comment.created_at,
            })
            self._conn.execute(
                "INSERT INTO graph_task_comments (id, task_id, data, created_at) VALUES (?, ?, ?, ?)",
                (comment.id, comment.task_id, data, comment.created_at),
            )
            self._conn.commit()

    def _get_comments_sync(self, task_id: str) -> list[TaskComment]:
        with self._lock:
            if self._namespace:
                cur = self._conn.execute(
                    """
                    SELECT c.data
                    FROM graph_task_comments c
                    JOIN graph_tasks t ON t.id = c.task_id
                    WHERE c.task_id = ? AND t.namespace = ?
                    ORDER BY c.created_at
                    """,
                    (task_id, self._namespace),
                )
            else:
                cur = self._conn.execute(
                    "SELECT data FROM graph_task_comments WHERE task_id = ? ORDER BY created_at",
                    (task_id,),
                )
            return [TaskComment(**json.loads(r[0])) for r in cur.fetchall()]

    def _goal_ancestry_sync(self, task_id: str) -> GoalAncestry | None:
        with self._lock:
            if self._namespace:
                cur = self._conn.execute(
                    """
                    WITH RECURSIVE ancestry(id, parent_task_id, data) AS (
                        SELECT id, parent_task_id, data
                        FROM graph_tasks
                        WHERE id = ? AND namespace = ?
                        UNION ALL
                        SELECT t.id, t.parent_task_id, t.data
                        FROM graph_tasks t
                        JOIN ancestry a ON t.id = a.parent_task_id
                        WHERE t.namespace = ?
                    )
                    SELECT data FROM ancestry
                    """,
                    (task_id, self._namespace, self._namespace),
                )
            else:
                cur = self._conn.execute(
                    """
                    WITH RECURSIVE ancestry(id, parent_task_id, data) AS (
                        SELECT id, parent_task_id, data FROM graph_tasks WHERE id = ?
                        UNION ALL
                        SELECT t.id, t.parent_task_id, t.data
                        FROM graph_tasks t JOIN ancestry a ON t.id = a.parent_task_id
                    )
                    SELECT data FROM ancestry
                    """,
                    (task_id,),
                )
            rows = cur.fetchall()
        if not rows:
            return None
        tasks = [self._deser(r[0]) for r in rows]
        root = tasks[-1]
        if not root.goal_id:
            return None
        chain = tuple(t.id for t in reversed(tasks))
        return GoalAncestry(root_goal_id=root.goal_id, chain=chain)

    # --- DAG scheduling helpers ---

    def _get_ready_sync(self) -> list[GraphTaskItem]:
        with self._lock:
            if self._namespace:
                cur = self._conn.execute(
                    "SELECT data FROM graph_tasks WHERE namespace = ?", (self._namespace,),
                )
            else:
                cur = self._conn.execute("SELECT data FROM graph_tasks")
            all_tasks: dict[str, GraphTaskItem] = {}
            for r in cur.fetchall():
                t = self._deser(r[0])
                all_tasks[t.id] = t
        ready: list[GraphTaskItem] = []
        for task in all_tasks.values():
            if task.status != TaskStatus.TODO:
                continue
            if task.checkout_agent_id is not None:
                continue
            if task.dependencies:
                all_done = all(
                    (dep := all_tasks.get(dep_id)) is not None and dep.status == TaskStatus.DONE
                    for dep_id in task.dependencies
                )
                if not all_done:
                    continue
            ready.append(task)
        return ready

    def _get_blocked_by_sync(self, task_id: str) -> list[GraphTaskItem]:
        with self._lock:
            params: list[Any] = [task_id]
            query = self._ns_filter("SELECT data FROM graph_tasks WHERE id = ?", params)
            cur = self._conn.execute(query, params)
            row = cur.fetchone()
            if not row:
                return []
            task = self._deser(row[0])
            if not task.dependencies:
                return []
            placeholders = ",".join("?" * len(task.dependencies))
            dep_params: list[Any] = list(task.dependencies)
            dep_query = f"SELECT data FROM graph_tasks WHERE id IN ({placeholders})"
            if self._namespace:
                dep_query += " AND namespace = ?"
                dep_params.append(self._namespace)
            cur2 = self._conn.execute(dep_query, dep_params)
            blockers: list[GraphTaskItem] = []
            for r in cur2.fetchall():
                t = self._deser(r[0])
                if t.status != TaskStatus.DONE:
                    blockers.append(t)
            return blockers

    # --- Async API ---

    async def create_task(self, task: GraphTaskItem) -> None:
        await asyncio.to_thread(self._create_sync, task)

    async def checkout_task(self, task_id: str, agent_id: str) -> GraphTaskItem | None:
        return await asyncio.to_thread(self._checkout_sync, task_id, agent_id)

    async def complete_task(self, task_id: str) -> bool:
        return await asyncio.to_thread(self._complete_sync, task_id)

    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]:
        return await asyncio.to_thread(self._subtasks_sync, task_id)

    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]:
        tasks = await asyncio.to_thread(self._list_sync)
        if "status" in filters:
            tasks = [t for t in tasks if t.status == filters["status"]]
        if "assignee_agent_id" in filters:
            tasks = [t for t in tasks if t.assignee_agent_id == filters["assignee_agent_id"]]
        return tasks

    async def add_comment(self, comment: TaskComment) -> None:
        await asyncio.to_thread(self._add_comment_sync, comment)

    async def get_comments(self, task_id: str) -> list[TaskComment]:
        return await asyncio.to_thread(self._get_comments_sync, task_id)

    async def get_thread(self, task_id: str) -> list[TaskComment]:
        """Get all comments for a task and its subtasks (recursive)."""
        return await asyncio.to_thread(self._get_thread_sync, task_id)

    def _get_thread_sync(self, task_id: str) -> list[TaskComment]:
        with self._lock:
            # Collect subtree task IDs via recursive CTE
            if self._namespace:
                cur = self._conn.execute(
                    """
                    WITH RECURSIVE sub(id) AS (
                        SELECT id FROM graph_tasks WHERE id = ? AND namespace = ?
                        UNION ALL
                        SELECT t.id
                        FROM graph_tasks t
                        JOIN sub s ON t.parent_task_id = s.id
                        WHERE t.namespace = ?
                    )
                    SELECT id FROM sub
                    """,
                    (task_id, self._namespace, self._namespace),
                )
            else:
                cur = self._conn.execute(
                    """
                    WITH RECURSIVE sub(id) AS (
                        SELECT id FROM graph_tasks WHERE id = ?
                        UNION ALL
                        SELECT t.id FROM graph_tasks t JOIN sub s ON t.parent_task_id = s.id
                    )
                    SELECT id FROM sub
                    """,
                    (task_id,),
                )
            task_ids = [r[0] for r in cur.fetchall()]
            if not task_ids:
                return []
            placeholders = ",".join("?" * len(task_ids))
            cur2 = self._conn.execute(
                f"SELECT data FROM graph_task_comments WHERE task_id IN ({placeholders}) ORDER BY created_at",
                task_ids,
            )
            return [TaskComment(**json.loads(r[0])) for r in cur2.fetchall()]

    async def get_ready_tasks(self) -> list[GraphTaskItem]:
        return await asyncio.to_thread(self._get_ready_sync)

    async def get_blocked_by(self, task_id: str) -> list[GraphTaskItem]:
        return await asyncio.to_thread(self._get_blocked_by_sync, task_id)

    async def cancel_task(self, task_id: str) -> bool:
        return await asyncio.to_thread(self._cancel_sync, task_id)

    async def block_task(self, task_id: str, reason: str) -> bool:
        return await asyncio.to_thread(self._block_sync, task_id, reason)

    async def unblock_task(self, task_id: str) -> bool:
        return await asyncio.to_thread(self._unblock_sync, task_id)

    async def get_goal_ancestry(self, task_id: str) -> GoalAncestry | None:
        return await asyncio.to_thread(self._goal_ancestry_sync, task_id)
