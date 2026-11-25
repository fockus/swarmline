"""Atomic point edits of a todo list - one pure function shared by every provider.

``apply_todo_ops`` applies a batch of ``add``/``update``/``remove`` operations to a
list and returns the new list. The batch is all-or-nothing: the first invalid
operation raises ``TodoEditError`` and the input list is never touched. Several items may
be ``in_progress`` at once: work delegated to parallel sub-agents is legitimately concurrent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, cast, get_args

from swarmline.todo.types import TodoItem

TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]
TODO_STATUSES: tuple[TodoStatus, ...] = get_args(TodoStatus)
HINT_START_NEXT = "mark the item you start next as in_progress"
_ID_ATTEMPTS = 8


class TodoEditError(ValueError):
    """A rejected batch: ``op_index`` is the offending operation (None: whole list)."""

    def __init__(self, op_index: int | None, reason: str) -> None:
        self.op_index = op_index
        self.reason = reason
        prefix = f"op {op_index}: " if op_index is not None else ""
        super().__init__(prefix + reason)


@dataclass(frozen=True)
class TodoEditResult:
    """The list after a successful batch, plus a nudge for the model (or None)."""

    items: list[TodoItem]
    hint: str | None = None


def next_step_hint(items: Sequence[TodoItem]) -> str | None:
    """Nudge when pending work exists but nothing is marked as started."""
    statuses = {t.status for t in items}
    started = "in_progress" in statuses
    return HINT_START_NEXT if "pending" in statuses and not started else None


def _text(op: Mapping[str, Any], key: str, index: int) -> str:
    value = op.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TodoEditError(index, f"{key} must be a non-empty string")
    return value


def _status(
    op: Mapping[str, Any], index: int, default: TodoStatus | None
) -> TodoStatus | None:
    value = op.get("status", default)
    if value is not None and value not in TODO_STATUSES:
        raise TodoEditError(
            index, f"status must be one of {', '.join(TODO_STATUSES)}, got {value!r}"
        )
    return cast("TodoStatus | None", value)


def _position(items: list[TodoItem], item_id: str, index: int) -> int:
    for pos, item in enumerate(items):
        if item.id == item_id:
            return pos
    raise TodoEditError(index, f"unknown id {item_id!r}")


def _fresh_id(items: list[TodoItem], new_id: Callable[[], str], index: int) -> str:
    taken = {t.id for t in items}
    for _ in range(_ID_ATTEMPTS):
        candidate = new_id()
        if candidate and candidate not in taken:
            return candidate
    raise TodoEditError(index, "could not allocate a unique id")


def apply_todo_ops(
    items: Sequence[TodoItem],
    ops: Sequence[Any],
    *,
    now: datetime,
    new_id: Callable[[], str],
    max_todos: int,
) -> TodoEditResult:
    """Apply ``ops`` in order to a copy of ``items``; raise on the first bad op."""
    if not ops:
        raise TodoEditError(None, "ops must be a non-empty array")
    result = list(items)
    for index, op in enumerate(ops):
        if not isinstance(op, Mapping):
            raise TodoEditError(index, "each op must be an object")
        kind = op.get("op")
        if kind == "add":
            content = _text(op, "content", index)
            status = _status(op, index, "pending") or "pending"
            after = op.get("after_id")
            end = len(result)
            pos = end if after is None else _position(result, str(after), index) + 1
            if len(result) >= max_todos:
                raise TodoEditError(index, f"max_todos ({max_todos}) reached")
            item_id = _fresh_id(result, new_id, index)
            result.insert(pos, TodoItem(item_id, content, status, now, now))
        elif kind == "update":
            pos = _position(result, _text(op, "id", index), index)
            status = _status(op, index, None)
            changes: dict[str, Any] = {"updated_at": now}
            if status is not None:
                changes["status"] = status
            if "content" in op:
                changes["content"] = _text(op, "content", index)
            result[pos] = replace(result[pos], **changes)
        elif kind == "remove":
            del result[_position(result, _text(op, "id", index), index)]
        else:
            raise TodoEditError(
                index, f"unknown op {kind!r}; use add, update or remove"
            )
    return TodoEditResult(items=result, hint=next_step_hint(result))
