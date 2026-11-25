"""apply_todo_ops: atomic point edits of a todo list (taskloom Sprint 1ce Stage 6, AGR-082)."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

import pytest

from swarmline.todo.ops import (
    HINT_START_NEXT,
    TodoEditError,
    apply_todo_ops,
)
from swarmline.todo.types import TodoItem

T0 = datetime(2026, 9, 1, tzinfo=UTC)
T1 = datetime(2026, 9, 27, tzinfo=UTC)


def _item(
    item_id: str, status: str = "pending", content: str | None = None
) -> TodoItem:
    return TodoItem(
        id=item_id,
        content=content or f"do {item_id}",
        status=status,  # type: ignore[arg-type]
        created_at=T0,
        updated_at=T0,
    )


def _ids() -> object:
    counter = count(1)
    return lambda: f"n{next(counter)}"


def _apply(items: list[TodoItem], ops: list[dict], **kw: object):
    params: dict[str, object] = {"now": T1, "new_id": _ids(), "max_todos": 100}
    params.update(kw)
    return apply_todo_ops(items, ops, **params)  # type: ignore[arg-type]


def test_add_generates_id_and_inserts_after_id() -> None:
    items = [_item("a", "in_progress"), _item("b")]

    result = _apply(
        items,
        [
            {"op": "add", "content": "middle", "after_id": "a"},
            {"op": "add", "content": "last"},
        ],
    )

    assert [(t.id, t.content) for t in result.items] == [
        ("a", "do a"),
        ("n1", "middle"),
        ("b", "do b"),
        ("n2", "last"),
    ]
    added = result.items[1]
    assert added.status == "pending"
    assert added.created_at == T1 and added.updated_at == T1


def test_update_changes_status_keeps_created_at() -> None:
    items = [_item("a", "in_progress"), _item("b")]

    result = _apply(
        items,
        [
            {"op": "update", "id": "a", "status": "completed"},
            {"op": "update", "id": "b", "status": "in_progress", "content": "do b now"},
        ],
    )

    a, b = result.items
    assert (a.status, a.created_at, a.updated_at) == ("completed", T0, T1)
    assert (b.status, b.content, b.created_at) == ("in_progress", "do b now", T0)
    assert result.hint is None


def test_remove_deletes_item() -> None:
    result = _apply(
        [_item("a", "in_progress"), _item("b")], [{"op": "remove", "id": "b"}]
    )

    assert [t.id for t in result.items] == ["a"]


def test_unknown_id_rejects_whole_batch_without_partial_apply() -> None:
    items = [_item("a", "in_progress"), _item("b")]
    snapshot = list(items)

    with pytest.raises(TodoEditError) as err:
        _apply(
            items,
            [
                {"op": "update", "id": "a", "status": "completed"},
                {"op": "remove", "id": "ghost"},
            ],
        )

    assert err.value.op_index == 1
    assert "ghost" in err.value.reason
    assert items == snapshot


def test_several_in_progress_items_allowed_for_parallel_work() -> None:
    """Parallel sub-agent work is legitimate: several items may be in_progress at once."""
    items = [_item("a", "in_progress"), _item("b"), _item("c")]

    result = _apply(
        items,
        [
            {"op": "update", "id": "b", "status": "in_progress"},
            {"op": "update", "id": "c", "status": "in_progress"},
        ],
    )

    assert [t.status for t in result.items] == ["in_progress"] * 3
    assert result.hint is None
    assert [t.status for t in items] == ["in_progress", "pending", "pending"]


def test_zero_in_progress_with_pending_returns_hint() -> None:
    result = _apply(
        [_item("a", "in_progress"), _item("b")],
        [{"op": "update", "id": "a", "status": "completed"}],
    )

    assert (
        result.hint == HINT_START_NEXT == "mark the item you start next as in_progress"
    )


def test_all_closed_list_has_no_hint() -> None:
    result = _apply(
        [_item("a", "in_progress")],
        [{"op": "update", "id": "a", "status": "completed"}],
    )

    assert result.hint is None


def test_max_todos_exceeded_rejected() -> None:
    items = [_item("a", "in_progress"), _item("b")]

    with pytest.raises(TodoEditError) as err:
        _apply(items, [{"op": "add", "content": "c"}], max_todos=2)

    assert err.value.op_index == 0
    assert "max_todos" in err.value.reason


def test_generated_id_collision_is_retried() -> None:
    ids = iter(["a", "a", "fresh"])

    result = _apply(
        [_item("a", "in_progress")],
        [{"op": "add", "content": "x"}],
        new_id=lambda: next(ids),
    )

    assert [t.id for t in result.items] == ["a", "fresh"]


@pytest.mark.parametrize(
    ("op", "fragment"),
    [
        ({"op": "add", "content": "   "}, "content"),
        ({"op": "add", "content": "x", "status": "done"}, "status"),
        ({"op": "update", "id": "a", "status": "blocked"}, "status"),
        ({"op": "update", "id": "a", "content": ""}, "content"),
        ({"op": "add", "content": "x", "after_id": "ghost"}, "ghost"),
        ({"op": "rename", "id": "a"}, "unknown op"),
        ({"op": "update"}, "id"),
        ("not-an-object", "object"),
    ],
)
def test_invalid_status_or_empty_content_rejected(op: object, fragment: str) -> None:
    items = [_item("a", "in_progress")]

    with pytest.raises(TodoEditError) as err:
        _apply(items, [op])  # type: ignore[list-item]

    assert fragment in err.value.reason
    assert err.value.op_index == 0
    assert str(err.value).startswith("op 0:")


def test_empty_batch_rejected() -> None:
    with pytest.raises(TodoEditError):
        _apply([_item("a")], [])


def test_id_allocation_gives_up_after_repeated_collisions() -> None:
    with pytest.raises(TodoEditError, match="unique id"):
        _apply([_item("a")], [{"op": "add", "content": "x"}], new_id=lambda: "a")
