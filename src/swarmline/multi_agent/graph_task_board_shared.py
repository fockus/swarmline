"""Shared serialization helpers for graph task board backends."""

from __future__ import annotations

import json
from typing import Any

from swarmline.multi_agent.graph_task_types import GraphTaskItem, TaskComment
from swarmline.multi_agent.task_types import TaskPriority, TaskStatus


def serialize_graph_task(task: GraphTaskItem) -> dict[str, Any]:
    """Serialize GraphTaskItem to a backend-neutral payload."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "assignee_agent_id": task.assignee_agent_id,
        "parent_task_id": task.parent_task_id,
        "goal_id": task.goal_id,
        "epic_id": task.epic_id,
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
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "metadata": task.metadata,
    }


def deserialize_graph_task(data: dict[str, Any]) -> GraphTaskItem:
    """Deserialize backend payload to GraphTaskItem."""
    return GraphTaskItem(
        id=data["id"],
        title=data["title"],
        description=data.get("description", ""),
        status=TaskStatus(data.get("status", "todo")),
        priority=TaskPriority(data.get("priority", "medium")),
        assignee_agent_id=data.get("assignee_agent_id"),
        parent_task_id=data.get("parent_task_id"),
        goal_id=data.get("goal_id"),
        epic_id=data.get("epic_id"),
        dod_criteria=tuple(data.get("dod_criteria", ())),
        dod_verified=data.get("dod_verified", False),
        checkout_agent_id=data.get("checkout_agent_id"),
        dependencies=tuple(data.get("dependencies", ())),
        delegated_by=data.get("delegated_by"),
        delegation_reason=data.get("delegation_reason"),
        estimated_effort=data.get("estimated_effort"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        progress=data.get("progress", 0.0),
        stage=data.get("stage", ""),
        blocked_reason=data.get("blocked_reason", ""),
        created_at=data.get("created_at", 0.0),
        updated_at=data.get("updated_at", 0.0),
        metadata=data.get("metadata", {}),
    )


def serialize_graph_task_json(task: GraphTaskItem) -> str:
    """Serialize GraphTaskItem to JSON string."""
    return json.dumps(serialize_graph_task(task))


def deserialize_graph_task_json(raw: str) -> GraphTaskItem:
    """Deserialize GraphTaskItem from JSON string."""
    return deserialize_graph_task(json.loads(raw))


def serialize_task_comment(comment: TaskComment) -> dict[str, Any]:
    """Serialize TaskComment to a backend-neutral payload."""
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "author_agent_id": comment.author_agent_id,
        "content": comment.content,
        "created_at": comment.created_at,
    }


def deserialize_task_comment(data: dict[str, Any]) -> TaskComment:
    """Deserialize backend payload to TaskComment."""
    return TaskComment(**data)
