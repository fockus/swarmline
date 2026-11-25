"""Plan Tools module."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from swarmline.runtime.types import ToolSpec

if TYPE_CHECKING:
    from swarmline.orchestration.manager import PlanManager

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "The plan's goal — what needs to be done. Task description for decomposition.",
        },
        "auto_execute": {
            "type": "boolean",
            "description": (
                "Automatically approve the generated plan (default: false). "
                "Execution is started separately via PlanManager.execute_plan."
            ),
            "default": False,
        },
    },
    "required": ["goal"],
}

_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plan_tools(
    manager: PlanManager,
    user_id: str,
    topic_id: str,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create plan tools."""

    async def plan_create(args: dict) -> str:
        """Create a plan for a complex task."""
        goal = args.get("goal", "")
        if not goal:
            return json.dumps({"status": "error", "message": "goal is required"})
        auto_execute = args.get("auto_execute", False)
        try:
            plan = await manager.create_plan(
                goal=goal,
                user_id=user_id,
                topic_id=topic_id,
                auto_approve=bool(auto_execute),
            )
            return json.dumps(
                {
                    "status": "ok",
                    "plan": {
                        "id": plan.id,
                        "goal": plan.goal,
                        "status": plan.status,
                        "steps": [
                            {
                                "id": s.id,
                                "description": s.description,
                                "status": s.status,
                            }
                            for s in plan.steps
                        ],
                    },
                }
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def plan_status(args: dict) -> str:
        """Show your plans."""
        try:
            plans = await manager.list_plans(user_id, topic_id)
            return json.dumps(
                {
                    "status": "ok",
                    "plans": [
                        {
                            "id": p.id,
                            "goal": p.goal,
                            "status": p.status,
                            "steps_total": len(p.steps),
                            "steps_completed": sum(
                                1 for s in p.steps if s.status == "completed"
                            ),
                        }
                        for p in plans
                    ],
                }
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "plan_create": ToolSpec(
            name="plan_create",
            description=(
                "Create a step-by-step plan for a complex task. Use when the task requires "
                "more than 3 steps. Steps advance automatically as you work through them — "
                "there is no separate step-update tool to call."
            ),
            parameters=_CREATE_SCHEMA,
        ),
        "plan_status": ToolSpec(
            name="plan_status",
            description="Show your current plans and their progress.",
            parameters=_STATUS_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "plan_create": plan_create,
        "plan_status": plan_status,
    }

    return specs, executors
