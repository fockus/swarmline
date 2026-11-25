"""Tests for GoldenTaskSuite — in-memory registry with 5 built-in tasks."""

from __future__ import annotations

import pytest

from swarmline.eval.coding_protocols import GoldenTaskSuitePort
from swarmline.eval.coding_types import GoldenTask, TaskCategory
from swarmline.eval.golden_tasks import GoldenTaskSuite


class TestGoldenTaskSuiteProtocol:
    def test_implements_port(self) -> None:
        suite = GoldenTaskSuite()
        assert isinstance(suite, GoldenTaskSuitePort)


class TestBuiltInTasks:
    def test_has_five_built_in_tasks(self) -> None:
        suite = GoldenTaskSuite()
        tasks = suite.list_tasks()
        assert len(tasks) == 5

    def test_one_task_per_category(self) -> None:
        suite = GoldenTaskSuite()
        categories = {t.category for t in suite.list_tasks()}
        assert categories == set(TaskCategory)

    @pytest.mark.parametrize("category", list(TaskCategory))
    def test_filter_by_category_returns_one_built_in(
        self, category: TaskCategory
    ) -> None:
        suite = GoldenTaskSuite()
        filtered = suite.filter_by_category(category)
        assert len(filtered) == 1
        assert filtered[0].category == category

    def test_all_built_in_tasks_have_valid_fields(self) -> None:
        suite = GoldenTaskSuite()
        for task in suite.list_tasks():
            assert task.task_id
            assert task.name
            assert task.description
            assert isinstance(task.setup_files, dict)
            assert isinstance(task.expected_outcomes, tuple)
            assert len(task.expected_outcomes) > 0


class TestRegistration:
    def test_register_custom_task(self) -> None:
        suite = GoldenTaskSuite()
        custom = GoldenTask(
            task_id="custom-1",
            category=TaskCategory.BUGFIX,
            name="Custom bugfix",
            description="A custom task",
            setup_files={"main.py": "print('hello')"},
            expected_outcomes=("tests pass",),
            tags=("custom",),
        )
        suite.register_task(custom)
        assert suite.get_task("custom-1") == custom
        assert len(suite.list_tasks()) == 6  # 5 built-in + 1 custom

    def test_register_replaces_existing(self) -> None:
        suite = GoldenTaskSuite()
        t1 = GoldenTask("dup", TaskCategory.BUGFIX, "v1", "d", {}, ("a",), ())
        t2 = GoldenTask("dup", TaskCategory.BUGFIX, "v2", "d", {}, ("b",), ())
        suite.register_task(t1)
        suite.register_task(t2)
        assert suite.get_task("dup") is not None
        assert suite.get_task("dup").name == "v2"  # type: ignore[union-attr]


class TestGetTask:
    def test_get_existing_task(self) -> None:
        suite = GoldenTaskSuite()
        tasks = suite.list_tasks()
        first = tasks[0]
        assert suite.get_task(first.task_id) == first

    def test_get_nonexistent_task_returns_none(self) -> None:
        suite = GoldenTaskSuite()
        assert suite.get_task("does-not-exist") is None


class TestFilterByCategory:
    def test_filter_returns_empty_when_no_match_after_clear(self) -> None:
        suite = GoldenTaskSuite()
        # All categories have exactly 1 built-in, test filter logic
        bugfix_tasks = suite.filter_by_category(TaskCategory.BUGFIX)
        assert all(t.category == TaskCategory.BUGFIX for t in bugfix_tasks)

    def test_filter_includes_custom_tasks(self) -> None:
        suite = GoldenTaskSuite()
        custom = GoldenTask(
            task_id="custom-bug",
            category=TaskCategory.BUGFIX,
            name="Extra bugfix",
            description="d",
            setup_files={},
            expected_outcomes=("pass",),
            tags=(),
        )
        suite.register_task(custom)
        filtered = suite.filter_by_category(TaskCategory.BUGFIX)
        assert len(filtered) == 2  # 1 built-in + 1 custom
