"""Tests for GraphTaskItem epic_id field (COG-02)."""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.task_types import TaskPriority, TaskStatus


class TestGraphTaskItemEpicIdDefault:
    """Backward compatibility: existing construction works without epic_id."""

    def test_default_construction_has_none_epic_id(self) -> None:
        task = GraphTaskItem(id="t1", title="task")
        assert task.epic_id is None

    def test_existing_fields_preserved_with_default_epic_id(self) -> None:
        task = GraphTaskItem(
            id="t1",
            title="implement auth",
            description="Add JWT auth",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            assignee_agent_id="agent-1",
            goal_id="goal-42",
        )
        assert task.goal_id == "goal-42"
        assert task.epic_id is None
        assert task.status == TaskStatus.IN_PROGRESS


class TestGraphTaskItemEpicIdExplicit:
    """Explicit construction with epic_id."""

    def test_explicit_epic_id(self) -> None:
        task = GraphTaskItem(id="t1", title="task", epic_id="epic-42")
        assert task.epic_id == "epic-42"

    def test_goal_id_and_epic_id_coexist(self) -> None:
        task = GraphTaskItem(
            id="t1",
            title="task",
            goal_id="goal-1",
            epic_id="epic-7",
        )
        assert task.goal_id == "goal-1"
        assert task.epic_id == "epic-7"


class TestGraphTaskItemEpicIdReplace:
    """dataclasses.replace() works with epic_id."""

    def test_replace_epic_id(self) -> None:
        task = GraphTaskItem(id="t1", title="task")
        updated = dataclasses.replace(task, epic_id="epic-99")
        assert updated.epic_id == "epic-99"
        assert task.epic_id is None  # original unchanged

    def test_replace_preserves_other_fields(self) -> None:
        task = GraphTaskItem(
            id="t1",
            title="task",
            goal_id="goal-1",
            epic_id="epic-42",
        )
        updated = dataclasses.replace(task, epic_id="epic-99")
        assert updated.goal_id == "goal-1"
        assert updated.id == "t1"


class TestGraphTaskItemFrozen:
    """GraphTaskItem remains frozen with epic_id."""

    def test_frozen_rejects_epic_id_mutation(self) -> None:
        task = GraphTaskItem(id="t1", title="task", epic_id="epic-42")
        with pytest.raises(dataclasses.FrozenInstanceError):
            task.epic_id = "epic-99"  # type: ignore[misc]
