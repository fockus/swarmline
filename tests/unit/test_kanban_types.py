"""Tests for kanban domain types — KanbanStatus, BlockKind, KanbanTask, TaskLink.

TDD: written before swarmline.kanban.types exists (must fail on import first).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from swarmline.kanban.types import BlockKind, KanbanStatus, KanbanTask, TaskLink

# ---------------------------------------------------------------------------
# KanbanStatus — exactly the nine hermes values
# ---------------------------------------------------------------------------


class TestKanbanStatus:
    """KanbanStatus must expose exactly the nine hermes statuses."""

    def test_kanban_status_has_exactly_nine_hermes_values(self) -> None:
        values = {member.value for member in KanbanStatus}
        assert values == {
            "triage",
            "todo",
            "scheduled",
            "ready",
            "running",
            "blocked",
            "review",
            "done",
            "archived",
        }

    def test_kanban_status_count_is_nine(self) -> None:
        assert len(KanbanStatus) == 9

    @pytest.mark.parametrize(
        ("member", "value"),
        [
            ("TRIAGE", "triage"),
            ("TODO", "todo"),
            ("SCHEDULED", "scheduled"),
            ("READY", "ready"),
            ("RUNNING", "running"),
            ("BLOCKED", "blocked"),
            ("REVIEW", "review"),
            ("DONE", "done"),
            ("ARCHIVED", "archived"),
        ],
    )
    def test_kanban_status_member_has_expected_value(
        self, member: str, value: str
    ) -> None:
        assert getattr(KanbanStatus, member).value == value

    def test_kanban_status_is_str_valued(self) -> None:
        assert KanbanStatus.TODO == "todo"
        assert isinstance(KanbanStatus.TODO, str)


# ---------------------------------------------------------------------------
# BlockKind — exactly the four typed values
# ---------------------------------------------------------------------------


class TestBlockKind:
    """BlockKind must expose exactly the four typed block reasons."""

    def test_block_kind_has_exactly_four_typed_values(self) -> None:
        values = {member.value for member in BlockKind}
        assert values == {"dependency", "needs_input", "capability", "transient"}

    def test_block_kind_count_is_four(self) -> None:
        assert len(BlockKind) == 4

    @pytest.mark.parametrize(
        ("member", "value"),
        [
            ("DEPENDENCY", "dependency"),
            ("NEEDS_INPUT", "needs_input"),
            ("CAPABILITY", "capability"),
            ("TRANSIENT", "transient"),
        ],
    )
    def test_block_kind_member_has_expected_value(
        self, member: str, value: str
    ) -> None:
        assert getattr(BlockKind, member).value == value


# ---------------------------------------------------------------------------
# KanbanTask — defaults, immutability, multi-parent
# ---------------------------------------------------------------------------


class TestKanbanTaskDefaults:
    """A new task constructed with only id+title gets the documented defaults."""

    def test_kanban_task_with_id_and_title_only_defaults_to_todo_status(self) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.status == KanbanStatus.TODO

    def test_kanban_task_with_id_and_title_only_defaults_block_recurrences_to_zero(
        self,
    ) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.block_recurrences == 0

    def test_kanban_task_with_id_and_title_only_defaults_to_no_parents(self) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.parent_ids == ()

    def test_kanban_task_with_id_and_title_only_defaults_block_kind_to_none(
        self,
    ) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.block_kind is None

    def test_kanban_task_with_id_and_title_only_defaults_metadata_to_empty_dict(
        self,
    ) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.metadata == {}

    def test_kanban_task_metadata_default_is_not_shared_between_instances(self) -> None:
        first = KanbanTask(id="t-1", title="First")
        second = KanbanTask(id="t-2", title="Second")
        first.metadata["k"] = "v"
        assert second.metadata == {}


class TestKanbanTaskMultiParent:
    """parent_ids models the multi-parent task_links relation."""

    def test_kanban_task_parent_ids_accepts_multiple_parents(self) -> None:
        task = KanbanTask(id="child-1", title="Sub-card", parent_ids=("p-1", "p-2"))
        assert task.parent_ids == ("p-1", "p-2")
        assert len(task.parent_ids) == 2

    def test_kanban_task_parent_ids_accepts_single_parent(self) -> None:
        task = KanbanTask(id="child-1", title="Sub-card", parent_ids=("p-1",))
        assert task.parent_ids == ("p-1",)


class TestKanbanTaskBlockedState:
    """block_kind + block_recurrences record why/how-often a card re-blocked."""

    def test_kanban_task_can_carry_block_kind_and_recurrences(self) -> None:
        task = KanbanTask(
            id="t-1",
            title="Blocked card",
            status=KanbanStatus.BLOCKED,
            block_kind=BlockKind.NEEDS_INPUT,
            block_recurrences=3,
        )
        assert task.status == KanbanStatus.BLOCKED
        assert task.block_kind == BlockKind.NEEDS_INPUT
        assert task.block_recurrences == 3


class TestKanbanTaskAssignment:
    """assignee/claimed_at/last_heartbeat_at — Sprint J kanban-unification fields.

    Optional, default None (backward compatible with every pre-existing
    caller that constructs a `KanbanTask` with only id/title).
    """

    def test_kanban_task_with_id_and_title_only_defaults_assignee_to_none(self) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.assignee is None

    def test_kanban_task_with_id_and_title_only_defaults_claimed_at_to_none(
        self,
    ) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.claimed_at is None

    def test_kanban_task_with_id_and_title_only_defaults_last_heartbeat_at_to_none(
        self,
    ) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        assert task.last_heartbeat_at is None

    def test_kanban_task_can_carry_assignee_and_liveness_timestamps(self) -> None:
        task = KanbanTask(
            id="t-1",
            title="Claimed card",
            assignee="claude-sonnet-4",
            claimed_at="2026-07-20T00:00:00+00:00",
            last_heartbeat_at="2026-07-20T00:01:00+00:00",
        )
        assert task.assignee == "claude-sonnet-4"
        assert task.claimed_at == "2026-07-20T00:00:00+00:00"
        assert task.last_heartbeat_at == "2026-07-20T00:01:00+00:00"


class TestKanbanTaskImmutability:
    """KanbanTask is frozen — mutation must raise."""

    def test_kanban_task_is_frozen_raises_on_status_mutation(self) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        with pytest.raises(FrozenInstanceError):
            task.status = KanbanStatus.DONE  # type: ignore[misc]

    def test_kanban_task_is_frozen_raises_on_title_mutation(self) -> None:
        task = KanbanTask(id="t-1", title="Do the thing")
        with pytest.raises(FrozenInstanceError):
            task.title = "Renamed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TaskLink — multi-parent link model
# ---------------------------------------------------------------------------


class TestTaskLink:
    """TaskLink models one edge of the multi-parent task_links relation."""

    def test_task_link_holds_parent_and_child_ids(self) -> None:
        link = TaskLink(parent_id="p-1", child_id="c-1")
        assert link.parent_id == "p-1"
        assert link.child_id == "c-1"

    def test_task_link_is_frozen_raises_on_mutation(self) -> None:
        link = TaskLink(parent_id="p-1", child_id="c-1")
        with pytest.raises(FrozenInstanceError):
            link.parent_id = "p-2"  # type: ignore[misc]
