"""Contract tests for `KanbanRetitle` — update a card's title (Sprint J fix-cycle 1, M-3).

TDD: written before `swarmline.kanban.store.KanbanRetitle` exists (must fail
on import first). ONE shared contract test parametrized over BOTH adapters
(InMemory + SQLite), same convention as `test_kanban_store.py`/
`test_kanban_assignment.py`.

Closes a real gap found by codex round 1: todo->kanban sync claimed
"drift-proof" but never propagated a changed todo `content` onto its
mirrored card's title — `update_title` is the missing primitive that lets
the application layer do that without touching `status`.
"""

from __future__ import annotations

import pytest

from swarmline.kanban.store import KanbanRetitle
from swarmline.kanban.types import KanbanTask

# ---------------------------------------------------------------------------
# Fixtures — same contract test runs against every adapter
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request: pytest.FixtureRequest):
    if request.param == "inmemory":
        from swarmline.kanban.inmemory import InMemoryKanbanStore

        return InMemoryKanbanStore()

    from swarmline.kanban.sqlite import SqliteKanbanStore

    return SqliteKanbanStore()


def _task(task_id: str, title: str = "Task", **kwargs: object) -> KanbanTask:
    return KanbanTask(id=task_id, title=title, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Protocol shape (ISP)
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_adapter_satisfies_kanban_retitle_protocol(self, store) -> None:
        assert isinstance(store, KanbanRetitle)

    def test_kanban_retitle_protocol_has_at_most_five_methods(self) -> None:
        methods = [
            name
            for name in vars(KanbanRetitle)
            if not name.startswith("_") and callable(getattr(KanbanRetitle, name))
        ]
        assert len(methods) <= 5


# ---------------------------------------------------------------------------
# update_title
# ---------------------------------------------------------------------------


class TestUpdateTitle:
    async def test_update_title_changes_the_stored_title(self, store) -> None:
        await store.create_task(_task("t1", "Old title"))

        updated = await store.update_title("t1", "New title")

        assert updated.title == "New title"
        refetched = (await store.list_tasks())[0]
        assert refetched.title == "New title"

    async def test_update_title_does_not_change_status(self, store) -> None:
        from swarmline.kanban.types import KanbanStatus

        await store.create_task(_task("t1", status=KanbanStatus.RUNNING))

        updated = await store.update_title("t1", "Renamed")

        assert updated.status == KanbanStatus.RUNNING

    async def test_update_title_unknown_id_raises(self, store) -> None:
        with pytest.raises(ValueError):
            await store.update_title("missing", "New title")
