"""Plan Store backends: InMemory, SQLite, PostgreSQL.

All backends implement the PlanStore protocol (4 methods, ISP).
Multi-tenant: plans are scoped by (user_id, topic_id) namespace.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from swarmline.orchestration.types import Plan, PlanStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers (Plan ↔ JSON)
# ---------------------------------------------------------------------------


def _step_to_dict(step: PlanStep) -> dict[str, Any]:
    """Serialize PlanStep to dict (recursive for substeps)."""
    return {
        "id": step.id,
        "description": step.description,
        "status": step.status,
        "result": step.result,
        "substeps": [_step_to_dict(s) for s in step.substeps],
        "dod_criteria": list(step.dod_criteria),
        "dod_verified": step.dod_verified,
        "verification_log": step.verification_log,
    }


def _dict_to_step(data: dict[str, Any]) -> PlanStep:
    """Deserialize dict to PlanStep (recursive for substeps)."""
    return PlanStep(
        id=data["id"],
        description=data["description"],
        status=data.get("status", "pending"),
        result=data.get("result"),
        substeps=[_dict_to_step(s) for s in data.get("substeps", [])],
        dod_criteria=tuple(data.get("dod_criteria", ())),
        dod_verified=data.get("dod_verified", False),
        verification_log=data.get("verification_log"),
    )


def _plan_to_row(plan: Plan, user_id: str, topic_id: str) -> dict[str, Any]:
    """Serialize Plan to a flat dict for DB storage."""
    return {
        "id": plan.id,
        "user_id": user_id,
        "topic_id": topic_id,
        "goal": plan.goal,
        "status": plan.status,
        "approved_by": plan.approved_by,
        "steps_json": json.dumps([_step_to_dict(s) for s in plan.steps]),
        "created_at": plan.created_at.isoformat(),
    }


def _row_to_plan(row: Any) -> Plan:
    """Deserialize a DB row to Plan."""
    steps_raw = row.steps_json
    if isinstance(steps_raw, str):
        steps_data = json.loads(steps_raw)
    else:
        steps_data = steps_raw  # Postgres JSONB returns list directly

    steps = [_dict_to_step(d) for d in steps_data]
    created_at = row.created_at
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return Plan(
        id=row.id,
        goal=row.goal,
        steps=steps,
        created_at=created_at,
        status=row.status,
        approved_by=row.approved_by,
    )


# ---------------------------------------------------------------------------
# InMemoryPlanStore
# ---------------------------------------------------------------------------


class InMemoryPlanStore:
    """In-memory PlanStore with multi-tenant namespace isolation.

    Namespace is set via set_namespace(user_id, topic_id).
    save() binds the plan to the current namespace.
    list_plans() filters by namespace.
    """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._ownership: dict[
            str, tuple[str, str]
        ] = {}  # plan_id → (user_id, topic_id)
        self._ns_user: str = ""
        self._ns_topic: str = ""

    def set_namespace(self, user_id: str, topic_id: str) -> None:
        """Set the namespace for save/list operations."""
        self._ns_user = user_id
        self._ns_topic = topic_id

    async def save(self, plan: Plan) -> None:
        """Save or update plan. Binds to current namespace."""
        self._plans[plan.id] = plan
        if self._ns_user or self._ns_topic:
            self._ownership[plan.id] = (self._ns_user, self._ns_topic)

    async def load(self, plan_id: str) -> Plan | None:
        """Load plan by ID."""
        plan = self._plans.get(plan_id)
        if plan is None:
            return None
        if not self._namespace_matches(plan_id):
            return None
        return plan

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans filtered by namespace."""
        if not user_id and not topic_id:
            return list(self._plans.values())
        result: list[Plan] = []
        for plan_id, plan in self._plans.items():
            owner = self._ownership.get(plan_id, ("", ""))
            if (not user_id or owner[0] == user_id) and (
                not topic_id or owner[1] == topic_id
            ):
                result.append(plan)
        return result

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Atomically update a step within a plan."""
        plan = self._plans.get(plan_id)
        if plan is None:
            return
        try:
            updated = plan.update_step(step)
            self._plans[plan_id] = updated
        except ValueError:
            logger.warning(
                "update_step: step %r not found in plan %r", step.id, plan_id
            )

    def _namespace_matches(self, plan_id: str) -> bool:
        if not self._ns_user and not self._ns_topic:
            return True
        owner = self._ownership.get(plan_id)
        if owner is None:
            return False
        return (not self._ns_user or owner[0] == self._ns_user) and (
            not self._ns_topic or owner[1] == self._ns_topic
        )


# ---------------------------------------------------------------------------
# SQLitePlanStore
# ---------------------------------------------------------------------------


class SQLitePlanStore:
    """SQLite-backed PlanStore (SQLAlchemy async).

    Requires ``aiosqlite`` and ``sqlalchemy[asyncio]``.
    Schema must be created externally (see SQLITE_PLAN_SCHEMA).
    """

    def __init__(self, session_factory: Any) -> None:
        self._sf: Any = session_factory
        self._ns_user: str = ""
        self._ns_topic: str = ""

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[Any]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    def set_namespace(self, user_id: str, topic_id: str) -> None:
        """Set the namespace for save/list operations."""
        self._ns_user = user_id
        self._ns_topic = topic_id

    async def save(self, plan: Plan) -> None:
        """Save or update plan (INSERT OR REPLACE)."""
        from sqlalchemy import text

        user_id = self._ns_user
        topic_id = self._ns_topic
        row = _plan_to_row(plan, user_id, topic_id)

        async with self._session(commit=True) as session:
            await session.execute(
                text("""
                    INSERT OR REPLACE INTO plans
                        (id, user_id, topic_id, goal, status, approved_by, steps_json, created_at, updated_at)
                    VALUES
                        (:id, :user_id, :topic_id, :goal, :status, :approved_by, :steps_json, :created_at, CURRENT_TIMESTAMP)
                """),
                row,
            )

    async def load(self, plan_id: str) -> Plan | None:
        """Load plan by ID."""
        from sqlalchemy import text

        where, params = _namespace_filter_sql(self._ns_user, self._ns_topic)
        params["id"] = plan_id
        async with self._session() as session:
            result = await session.execute(
                text(f"SELECT * FROM plans WHERE id = :id {where}"),
                params,
            )
            row = result.first()
            return _row_to_plan(row) if row else None

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans filtered by namespace."""
        from sqlalchemy import text

        conditions = []
        params: dict[str, str] = {}
        if user_id:
            conditions.append("user_id = :user_id")
            params["user_id"] = user_id
        if topic_id:
            conditions.append("topic_id = :topic_id")
            params["topic_id"] = topic_id

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM plans {where} ORDER BY created_at DESC"

        async with self._session() as session:
            result = await session.execute(text(query), params)
            return [_row_to_plan(row) for row in result.fetchall()]

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Load plan, update step, save back (atomic)."""
        plan = await self.load(plan_id)
        if plan is None:
            return
        try:
            updated = plan.update_step(step)
            await self.save(updated)
        except ValueError:
            logger.warning(
                "update_step: step %r not found in plan %r", step.id, plan_id
            )


# ---------------------------------------------------------------------------
# PostgresPlanStore
# ---------------------------------------------------------------------------


class PostgresPlanStore:
    """PostgreSQL-backed PlanStore (SQLAlchemy async + asyncpg).

    Requires ``asyncpg`` and ``sqlalchemy[asyncio]``.
    Uses JSONB for steps_json. Schema must be created externally.
    """

    def __init__(self, session_factory: Any) -> None:
        self._sf: Any = session_factory
        self._ns_user: str = ""
        self._ns_topic: str = ""

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[Any]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    def set_namespace(self, user_id: str, topic_id: str) -> None:
        """Set the namespace for save/list operations."""
        self._ns_user = user_id
        self._ns_topic = topic_id

    async def save(self, plan: Plan) -> None:
        """Save or update plan (INSERT ON CONFLICT DO UPDATE)."""
        from sqlalchemy import text

        user_id = self._ns_user
        topic_id = self._ns_topic
        row = _plan_to_row(plan, user_id, topic_id)

        async with self._session(commit=True) as session:
            await session.execute(
                text("""
                    INSERT INTO plans
                        (id, user_id, topic_id, goal, status, approved_by, steps_json, created_at, updated_at)
                    VALUES
                        (:id, :user_id, :topic_id, :goal, :status, :approved_by,
                         CAST(:steps_json AS jsonb), :created_at, now())
                    ON CONFLICT (id) DO UPDATE SET
                        goal = EXCLUDED.goal,
                        status = EXCLUDED.status,
                        approved_by = EXCLUDED.approved_by,
                        steps_json = EXCLUDED.steps_json,
                        updated_at = now()
                """),
                row,
            )

    async def load(self, plan_id: str) -> Plan | None:
        """Load plan by ID."""
        from sqlalchemy import text

        where, params = _namespace_filter_sql(self._ns_user, self._ns_topic)
        params["id"] = plan_id
        async with self._session() as session:
            result = await session.execute(
                text(f"SELECT * FROM plans WHERE id = :id {where}"),
                params,
            )
            row = result.first()
            return _row_to_plan(row) if row else None

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans filtered by namespace."""
        from sqlalchemy import text

        conditions = []
        params: dict[str, str] = {}
        if user_id:
            conditions.append("user_id = :user_id")
            params["user_id"] = user_id
        if topic_id:
            conditions.append("topic_id = :topic_id")
            params["topic_id"] = topic_id

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM plans {where} ORDER BY created_at DESC"

        async with self._session() as session:
            result = await session.execute(text(query), params)
            return [_row_to_plan(row) for row in result.fetchall()]

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Load plan, update step, save back (atomic)."""
        plan = await self.load(plan_id)
        if plan is None:
            return
        try:
            updated = plan.update_step(step)
            await self.save(updated)
        except ValueError:
            logger.warning(
                "update_step: step %r not found in plan %r", step.id, plan_id
            )


# ---------------------------------------------------------------------------
# Schema constants (for tests and migrations)
# ---------------------------------------------------------------------------

SQLITE_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    approved_by TEXT,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_plans_owner ON plans (user_id, topic_id);
"""

POSTGRES_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    approved_by TEXT,
    steps_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_plans_owner ON plans (user_id, topic_id);
"""


def _namespace_filter_sql(user_id: str, topic_id: str) -> tuple[str, dict[str, str]]:
    clauses: list[str] = []
    params: dict[str, str] = {}
    if user_id:
        clauses.append("user_id = :ns_user_id")
        params["ns_user_id"] = user_id
    if topic_id:
        clauses.append("topic_id = :ns_topic_id")
        params["ns_topic_id"] = topic_id
    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params
