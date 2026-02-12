"""Plan tools — инструменты планирования для агента.

Агент сам решает когда ему нужен план и вызывает plan_create.
Prompt addon описывает правила: когда планировать, когда не нужно.

KISS: 3 инструмента — create, status, execute.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cognitia.runtime.types import ToolSpec

if TYPE_CHECKING:
    from cognitia.orchestration.manager import PlanManager

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "Цель плана — что нужно сделать. Описание задачи для декомпозиции.",
        },
        "auto_execute": {
            "type": "boolean",
            "description": "Автоматически одобрить и начать выполнение (default: false).",
            "default": False,
        },
    },
    "required": ["goal"],
}

_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}

_EXECUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan_id": {
            "type": "string",
            "description": "ID плана для выполнения.",
        },
    },
    "required": ["plan_id"],
}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plan_tools(
    manager: PlanManager,
    user_id: str,
    topic_id: str,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Создать plan_* tools для агента.

    Args:
        manager: PlanManager с инжектированными PlannerMode и PlanStore.
        user_id: ID пользователя для namespace.
        topic_id: ID топика для namespace.

    Returns:
        Tuple: (specs, executors).
    """

    async def plan_create(args: dict) -> str:
        """Создать план для сложной задачи."""
        goal = args.get("goal", "")
        if not goal:
            return json.dumps({"status": "error", "message": "goal обязателен"})
        auto_execute = args.get("auto_execute", False)
        try:
            plan = await manager.create_plan(
                goal=goal, user_id=user_id, topic_id=topic_id,
                auto_approve=bool(auto_execute),
            )
            return json.dumps({
                "status": "ok",
                "plan": {
                    "id": plan.id,
                    "goal": plan.goal,
                    "status": plan.status,
                    "steps": [{"id": s.id, "description": s.description, "status": s.status} for s in plan.steps],
                },
            })
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def plan_status(args: dict) -> str:
        """Показать текущие планы."""
        try:
            plans = await manager.list_plans(user_id, topic_id)
            return json.dumps({
                "status": "ok",
                "plans": [
                    {
                        "id": p.id, "goal": p.goal, "status": p.status,
                        "steps_total": len(p.steps),
                        "steps_completed": sum(1 for s in p.steps if s.status == "completed"),
                    }
                    for p in plans
                ],
            })
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def plan_execute(args: dict) -> str:
        """Выполнить план по шагам."""
        plan_id = args.get("plan_id", "")
        if not plan_id:
            return json.dumps({"status": "error", "message": "plan_id обязателен"})
        try:
            completed: list[dict[str, str]] = []
            async for step in manager.execute_plan(plan_id):
                completed.append({
                    "id": step.id, "description": step.description,
                    "status": step.status, "result": step.result or "",
                })
            return json.dumps({"status": "ok", "completed_steps": completed})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "plan_create": ToolSpec(
            name="plan_create",
            description="Создать пошаговый план для сложной задачи. Используй когда задача требует >3 шагов.",
            parameters=_CREATE_SCHEMA,
        ),
        "plan_status": ToolSpec(
            name="plan_status",
            description="Показать текущие планы и их прогресс.",
            parameters=_STATUS_SCHEMA,
        ),
        "plan_execute": ToolSpec(
            name="plan_execute",
            description="Выполнить одобренный план по шагам.",
            parameters=_EXECUTE_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "plan_create": plan_create,
        "plan_status": plan_status,
        "plan_execute": plan_execute,
    }

    return specs, executors
