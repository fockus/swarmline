"""Team coordination tools for Swarmline MCP server."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog

from swarmline.mcp._session import StatefulSession
from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)

logger = structlog.get_logger(__name__)


def _agent_to_dict(record: AgentRecord) -> dict[str, Any]:
    """Serialize AgentRecord to a JSON-friendly dict."""
    d = asdict(record)
    d["status"] = record.status.value
    return d


def _task_to_dict(item: TaskItem) -> dict[str, Any]:
    """Serialize TaskItem to a JSON-friendly dict."""
    d = asdict(item)
    d["status"] = item.status.value
    d["priority"] = item.priority.value
    return d


async def team_register_agent(
    session: StatefulSession,
    id: str,
    name: str,
    role: str,
    parent_id: str | None = None,
    runtime_name: str = "thin",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register an agent in the team registry."""
    try:
        record = AgentRecord(
            id=id,
            name=name,
            role=role,
            parent_id=parent_id,
            runtime_name=runtime_name,
            metadata=metadata or {},
        )
        await session.agent_registry.register(record)
        logger.info("team_agent_registered", agent_id=id, role=role)
        return {"ok": True, "data": {"agent_id": id}}
    except ValueError as exc:
        logger.warning("team_register_agent_duplicate", agent_id=id, error=str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("team_register_agent_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def team_list_agents(
    session: StatefulSession,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List agents with optional role/status filters."""
    try:
        filters: AgentFilter | None = None
        if role is not None or status is not None:
            filters = AgentFilter(
                role=role,
                status=AgentStatus(status) if status is not None else None,
            )
        agents = await session.agent_registry.list_agents(filters)
        return {"ok": True, "data": [_agent_to_dict(a) for a in agents]}
    except Exception as exc:
        logger.warning("team_list_agents_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def team_create_task(
    session: StatefulSession,
    id: str,
    title: str,
    description: str = "",
    priority: str = "MEDIUM",
    assignee_agent_id: str | None = None,
) -> dict[str, Any]:
    """Create a task in the team task queue."""
    try:
        item = TaskItem(
            id=id,
            title=title,
            description=description,
            priority=TaskPriority(priority.lower()),
            assignee_agent_id=assignee_agent_id,
        )
        await session.task_queue.put(item)
        logger.info("team_task_created", task_id=id, priority=priority)
        return {"ok": True, "data": {"task_id": id}}
    except Exception as exc:
        logger.warning("team_create_task_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def team_claim_task(
    session: StatefulSession,
    assignee_agent_id: str | None = None,
) -> dict[str, Any]:
    """Claim the highest-priority available task from the queue."""
    try:
        filters: TaskFilter | None = None
        if assignee_agent_id is not None:
            filters = TaskFilter(assignee_agent_id=assignee_agent_id)
        task = await session.task_queue.get(filters)
        if task is None:
            return {"ok": False, "error": "No tasks available"}
        logger.info("team_task_claimed", task_id=task.id, assignee=assignee_agent_id)
        return {"ok": True, "data": {"task_id": task.id, "title": task.title}}
    except Exception as exc:
        logger.warning("team_claim_task_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def team_list_tasks(
    session: StatefulSession,
    status: str | None = None,
    priority: str | None = None,
    assignee_agent_id: str | None = None,
) -> dict[str, Any]:
    """List tasks with optional filters."""
    try:
        filters: TaskFilter | None = None
        if status is not None or priority is not None or assignee_agent_id is not None:
            filters = TaskFilter(
                status=TaskStatus(status) if status is not None else None,
                priority=TaskPriority(priority.lower())
                if priority is not None
                else None,
                assignee_agent_id=assignee_agent_id,
            )
        tasks = await session.task_queue.list_tasks(filters)
        return {"ok": True, "data": [_task_to_dict(t) for t in tasks]}
    except Exception as exc:
        logger.warning("team_list_tasks_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
