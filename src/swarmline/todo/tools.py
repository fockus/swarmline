"""Todo tools - todo_read, todo_write and todo_edit for agents.

Compatible with Claude Code TodoRead/TodoWrite; ``todo_edit`` is registered when
the provider also implements ``TodoEditProvider`` (point edits by id, atomic batch).
Standalone: works without sandbox and memory bank.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from swarmline.runtime.types import ToolSpec
from swarmline.todo.ops import TODO_STATUSES, next_step_hint
from swarmline.todo.protocols import TodoEditProvider, TodoProvider
from swarmline.todo.types import TodoItem

_STATUS_SCHEMA: dict[str, Any] = {"type": "string", "enum": list(TODO_STATUSES)}

_TODO_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status_filter": {
            **_STATUS_SCHEMA,
            "description": "Only return items with this status (optional)",
        },
    },
}

_TODO_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "content": {"type": "string"},
                    "status": _STATUS_SCHEMA,
                },
                "required": ["id", "content", "status"],
            },
            "description": "The complete list; items you omit are removed",
        },
    },
    "required": ["todos"],
}


def _op_schema(
    op: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"op": {"const": op}, **properties},
        "required": ["op", *required],
    }


_TODO_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ops": {
            "type": "array",
            "minItems": 1,
            "items": {
                "oneOf": [
                    _op_schema(
                        "add",
                        {
                            "content": {"type": "string"},
                            "status": {**_STATUS_SCHEMA, "default": "pending"},
                            "after_id": {
                                "type": "string",
                                "description": "Insert after this item (default: at the end)",
                            },
                        },
                        ["content"],
                    ),
                    _op_schema(
                        "update",
                        {
                            "id": {"type": "string"},
                            "status": _STATUS_SCHEMA,
                            "content": {"type": "string"},
                        },
                        ["id"],
                    ),
                    _op_schema("remove", {"id": {"type": "string"}}, ["id"]),
                ]
            },
            "description": "Edits applied in order, all or nothing",
        },
    },
    "required": ["ops"],
}

_READ_DESCRIPTION = "Read your todo list, optionally filtered by status."
_WRITE_DESCRIPTION = (
    "Replace your whole todo list. Pass every item (id, content, status); items you "
    "omit are removed. Mark the item you are working on in_progress; several items may be "
    "in_progress when work runs in parallel (for example, delegated to sub-agents)."
)
_EDIT_DESCRIPTION = (
    "Edit your todo list without rewriting it: add items (ids are assigned for you), "
    "update an item's status or text by id, or remove an item by id. The batch applies "
    "all or nothing. Mark the item you are working on in_progress; several items may be "
    "in_progress when work runs in parallel (for example, delegated to sub-agents)."
)
_LIST_SUFFIX = " Returns the updated list."


logger = logging.getLogger(__name__)
_STORE_UNAVAILABLE = "the todo list is unavailable right now; try again"


def _failure(tool: str, exc: Exception) -> str:
    """A validation error (``ValueError``, incl. ``TodoEditError``) is for the model;
    anything else is a store failure — logged in full, reported generically (no SQL,
    hosts or table names in the model's context)."""
    if isinstance(exc, ValueError):
        return _error(str(exc))
    logger.warning("%s: todo store failure", tool, exc_info=exc)
    return _error(_STORE_UNAVAILABLE)


def _error(message: str) -> str:
    return json.dumps({"status": "error", "message": message})


def _ok(items: Sequence[TodoItem], hint: str | None, full_list: bool) -> str:
    if not full_list:
        return json.dumps({"status": "ok", "count": len(items)})
    todos = [{"id": t.id, "content": t.content, "status": t.status} for t in items]
    return json.dumps({"status": "ok", "todos": todos, "hint": hint})


def _merge_written(
    raw_todos: list[Any], existing: Sequence[TodoItem], now: datetime
) -> list[TodoItem]:
    """Items to store: an id already on the list keeps its ``created_at``."""
    known = {t.id: t for t in existing}
    items: list[TodoItem] = []
    for raw in raw_todos:
        item_id = str(raw.get("id", ""))
        content = str(raw.get("content", ""))
        status = raw.get("status", "pending")
        prior = known.get(item_id)
        unchanged = prior is not None and (prior.content, prior.status) == (
            content,
            status,
        )
        items.append(
            TodoItem(
                id=item_id,
                content=content,
                status=status,
                created_at=prior.created_at if prior is not None else now,
                updated_at=prior.updated_at if unchanged and prior is not None else now,
            )
        )
    return items


def create_todo_tools(
    provider: TodoProvider,
    *,
    include_read: bool = True,
    full_list_response: bool = False,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create the todo tools for ``provider``.

    Args:
        provider: TodoProvider (InMemory, FS, DB). A provider that also implements
            ``TodoEditProvider`` additionally gets ``todo_edit``.
        include_read: register ``todo_read`` (off when the list reaches the model
            through tool responses and recitation instead).
        full_list_response: ``todo_write``/``todo_edit`` answer with the whole list
            ``[{id, content, status}]`` and a ``hint``; otherwise ``{"status", "count"}``.

    Returns:
        Tuple: (specs dict, executors dict).
    """
    suffix = _LIST_SUFFIX if full_list_response else ""

    async def todo_read_executor(args: dict) -> str:
        """Read todos with an optional status filter."""
        try:
            todos = await provider.read_todos()
            status_filter = args.get("status_filter")
            if status_filter:
                todos = [t for t in todos if t.status == status_filter]
            return json.dumps({"todos": [t.to_dict() for t in todos]})
        except Exception as e:
            return _failure("todo_read", e)

    async def todo_write_executor(args: dict) -> str:
        """Write todos (bulk replace)."""
        raw_todos = args.get("todos", [])
        if not isinstance(raw_todos, list):
            return _error("todos must be an array")
        try:
            items = _merge_written(
                raw_todos, await provider.read_todos(), datetime.now(tz=UTC)
            )
            await provider.write_todos(items)
            return _ok(items, next_step_hint(items), full_list_response)
        except Exception as e:
            return _failure("todo_write", e)

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}
    if include_read:
        specs["todo_read"] = ToolSpec(
            name="todo_read",
            description=_READ_DESCRIPTION,
            parameters=_TODO_READ_SCHEMA,
        )
        executors["todo_read"] = todo_read_executor
    specs["todo_write"] = ToolSpec(
        name="todo_write",
        description=_WRITE_DESCRIPTION + suffix,
        parameters=_TODO_WRITE_SCHEMA,
    )
    executors["todo_write"] = todo_write_executor

    if isinstance(provider, TodoEditProvider):
        editor: TodoEditProvider = provider

        async def todo_edit_executor(args: dict) -> str:
            """Apply an atomic batch of point edits."""
            ops = args.get("ops")
            if not isinstance(ops, list) or not ops:
                return _error("ops must be a non-empty array")
            try:
                result = await editor.apply_edit(ops)
            except Exception as e:  # TodoEditError names the op for the model
                return _failure("todo_edit", e)
            return _ok(result.items, result.hint, full_list_response)

        specs["todo_edit"] = ToolSpec(
            name="todo_edit",
            description=_EDIT_DESCRIPTION + suffix,
            parameters=_TODO_EDIT_SCHEMA,
        )
        executors["todo_edit"] = todo_edit_executor

    return specs, executors
