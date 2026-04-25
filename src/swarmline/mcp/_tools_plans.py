"""Plan tools for Swarmline MCP server."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from swarmline.mcp._session import StatefulSession
from swarmline.orchestration.types import Plan, PlanStep

logger = structlog.get_logger(__name__)


def _step_to_dict(step: PlanStep) -> dict[str, Any]:
    """Serialize a PlanStep to a plain dict."""
    return {
        "id": step.id,
        "description": step.description,
        "status": step.status,
        "result": step.result,
    }


def _plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Serialize a Plan to a plain dict."""
    return {
        "id": plan.id,
        "goal": plan.goal,
        "status": plan.status,
        "approved_by": plan.approved_by,
        "created_at": plan.created_at.isoformat(),
        "steps": [_step_to_dict(s) for s in plan.steps],
    }


async def plan_create(
    session: StatefulSession,
    goal: str,
    steps: list[str],
    user_id: str = "default",
    topic_id: str = "default",
) -> dict[str, Any]:
    """Create a new plan with the given goal and step descriptions."""
    try:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        plan_steps = [
            PlanStep(id=f"step-{uuid.uuid4().hex[:8]}", description=desc)
            for desc in steps
        ]
        plan = Plan(
            id=plan_id,
            goal=goal,
            steps=plan_steps,
            created_at=datetime.now(timezone.utc),
        )
        session.plan_store.set_namespace(user_id, topic_id)
        await session.plan_store.save(plan)
        return {"ok": True, "data": _plan_to_dict(plan)}
    except Exception as exc:
        logger.warning("plan_create_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def plan_get(
    session: StatefulSession,
    plan_id: str,
) -> dict[str, Any]:
    """Load a plan by its ID."""
    try:
        plan = await session.plan_store.load(plan_id)
        if plan is None:
            return {"ok": False, "error": f"Plan not found: {plan_id}"}
        return {"ok": True, "data": _plan_to_dict(plan)}
    except Exception as exc:
        logger.warning("plan_get_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def plan_list(
    session: StatefulSession,
    user_id: str = "default",
    topic_id: str = "default",
) -> dict[str, Any]:
    """List all plans in the given namespace."""
    try:
        plans = await session.plan_store.list_plans(user_id, topic_id)
        return {"ok": True, "data": [_plan_to_dict(p) for p in plans]}
    except Exception as exc:
        logger.warning("plan_list_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def plan_approve(
    session: StatefulSession,
    plan_id: str,
    approved_by: str = "user",
) -> dict[str, Any]:
    """Approve a draft plan, transitioning it to 'approved' status."""
    try:
        plan = await session.plan_store.load(plan_id)
        if plan is None:
            return {"ok": False, "error": f"Plan not found: {plan_id}"}
        updated = plan.approve(approved_by)  # ty: ignore[invalid-argument-type]  # Plan.approve(by) Literal narrow not propagated by ty
        await session.plan_store.save(updated)
        return {"ok": True, "data": _plan_to_dict(updated)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("plan_approve_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def plan_update_step(
    session: StatefulSession,
    plan_id: str,
    step_id: str,
    status: str,
    result: str | None = None,
) -> dict[str, Any]:
    """Update a step within a plan to a new status."""
    try:
        plan = await session.plan_store.load(plan_id)
        if plan is None:
            return {"ok": False, "error": f"Plan not found: {plan_id}"}

        target_step: PlanStep | None = None
        for step in plan.steps:
            if step.id == step_id:
                target_step = step
                break

        if target_step is None:
            return {"ok": False, "error": f"Step not found: {step_id}"}

        if status == "in_progress":
            updated_step = target_step.start()
        elif status == "completed":
            updated_step = target_step.complete(result or "")
        elif status == "failed":
            updated_step = target_step.fail(result or "")
        elif status == "skipped":
            updated_step = target_step.skip(result or "")
        else:
            return {"ok": False, "error": f"Invalid status: {status}"}

        updated_plan = plan.update_step(updated_step)
        await session.plan_store.save(updated_plan)
        return {"ok": True, "data": _step_to_dict(updated_step)}
    except Exception as exc:
        logger.warning("plan_update_step_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
