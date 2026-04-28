"""Integration tests for cancel/readiness/blockers flow on DefaultCodingTaskRuntime.

These exercise the 3 board methods that previously triggered ty unresolved-
attribute errors:
    coding_task_runtime.py:163  → board.cancel_task(task_id)
    coding_task_runtime.py:180  → board.get_ready_tasks()
    coding_task_runtime.py:184  → board.get_blocked_by(task_id)

Runtime behavior is unchanged by the type-hint fix (duck typing already
worked) — these tests lock the contract so future refactors cannot silently
break it.

Uses real `InMemoryGraphTaskBoard` + `InMemoryTaskSessionStore` (no mocks per
project rule "integration tests use real components, only LLM mocked").
"""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.orchestration.coding_task_runtime import DefaultCodingTaskRuntime
from swarmline.session.task_session_store import InMemoryTaskSessionStore

pytestmark = pytest.mark.integration


@pytest.fixture
def runtime():
    board = InMemoryGraphTaskBoard(namespace="coding")
    session_store = InMemoryTaskSessionStore()
    return DefaultCodingTaskRuntime(board, session_store, namespace="coding")


async def test_cancel_task_path_does_not_crash(
    runtime: DefaultCodingTaskRuntime,
) -> None:
    """End-to-end cancel flow exits without AttributeError.

    Path: create → start → cancel. Previously, type-checker flagged
    `self._board.cancel_task` as unresolved; runtime succeeded due to duck
    typing. This test ensures behavior preserved after type-hint fix.
    """
    await runtime.create_task("task-cancel", "Test cancel", session_id="s1")
    await runtime.start_task("task-cancel", agent_id="agent-1")

    cancelled = await runtime.cancel_task("task-cancel")
    assert cancelled is True

    # Idempotency: re-cancelling a cancelled task returns False
    cancelled_again = await runtime.cancel_task("task-cancel")
    assert cancelled_again is False


async def test_cancel_unknown_task_returns_false(
    runtime: DefaultCodingTaskRuntime,
) -> None:
    """cancel_task on non-existent task returns False (not crash)."""
    result = await runtime.cancel_task("nonexistent-task")
    assert result is False


async def test_is_ready_returns_bool_for_existing_task(
    runtime: DefaultCodingTaskRuntime,
) -> None:
    """is_ready() exercises board.get_ready_tasks() — must not AttributeError."""
    await runtime.create_task("task-ready", "Test ready", session_id="s1")

    # Just-created task with no deps → ready
    is_ready = await runtime.is_ready("task-ready")
    assert isinstance(is_ready, bool)


async def test_get_blockers_returns_list_for_existing_task(
    runtime: DefaultCodingTaskRuntime,
) -> None:
    """get_blockers() exercises board.get_blocked_by() — must return list of strings."""
    await runtime.create_task("task-no-blockers", "No blockers", session_id="s1")

    blockers = await runtime.get_blockers("task-no-blockers")
    assert isinstance(blockers, list)
    assert all(isinstance(b, str) for b in blockers)
    # Task with no dependencies has no blockers
    assert blockers == []


async def test_get_blockers_for_unknown_task_returns_empty_list(
    runtime: DefaultCodingTaskRuntime,
) -> None:
    """get_blockers on non-existent task: graceful empty-list (no AttributeError)."""
    blockers = await runtime.get_blockers("nonexistent-task")
    assert blockers == []
