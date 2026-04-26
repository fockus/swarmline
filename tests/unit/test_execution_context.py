"""Unit tests for ExecutionContext and ExecutionMode."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from swarmline.multi_agent.execution_context import ExecutionContext, ExecutionMode


class _FakeBoard:
    """Minimal board fake for testing."""

    def __init__(self, namespace: str = "") -> None:
        self.namespace = namespace


class TestExecutionMode:
    def test_isolated_value(self) -> None:
        assert ExecutionMode.ISOLATED.value == "isolated"

    def test_unified_value(self) -> None:
        assert ExecutionMode.UNIFIED.value == "unified"

    def test_is_str_enum(self) -> None:
        assert isinstance(ExecutionMode.ISOLATED, str)


class TestIsolatedMode:
    def test_create_isolated_mode(self) -> None:
        board = _FakeBoard("goal-a")
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
        )
        assert ctx.mode == ExecutionMode.ISOLATED

    def test_create_isolated_namespace(self) -> None:
        board = _FakeBoard("goal-a")
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
        )
        assert ctx.namespace == "goal-a"

    def test_create_isolated_namespaces_tuple(self) -> None:
        board = _FakeBoard("goal-a")
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
        )
        assert ctx.namespaces == ("goal-a",)

    def test_create_isolated_board_property(self) -> None:
        board = _FakeBoard("goal-a")
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
        )
        assert ctx.board is board

    def test_create_isolated_with_budget(self) -> None:
        board = _FakeBoard("goal-a")
        budget = MagicMock()
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
            budget_partition=budget,
        )
        assert ctx.budget is budget

    def test_create_isolated_with_event_bus(self) -> None:
        board = _FakeBoard("goal-a")
        bus = MagicMock()
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
            event_bus=bus,
        )
        assert ctx.event_bus is bus

    def test_create_isolated_get_board_by_namespace(self) -> None:
        board = _FakeBoard("goal-a")
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=board,
        )
        assert ctx.get_board("goal-a") is board


class TestUnifiedMode:
    def test_create_unified_mode(self) -> None:
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": _FakeBoard("goal-a"), "goal-b": _FakeBoard("goal-b")},
        )
        assert ctx.mode == ExecutionMode.UNIFIED

    def test_create_unified_namespaces(self) -> None:
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": _FakeBoard("goal-a"), "goal-b": _FakeBoard("goal-b")},
        )
        assert ctx.namespaces == ("goal-a", "goal-b")

    def test_create_unified_namespace_is_empty(self) -> None:
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": _FakeBoard("goal-a"), "goal-b": _FakeBoard("goal-b")},
        )
        assert ctx.namespace == ""

    def test_create_unified_get_board(self) -> None:
        board_a = _FakeBoard("goal-a")
        board_b = _FakeBoard("goal-b")
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": board_a, "goal-b": board_b},
        )
        assert ctx.get_board("goal-a") is board_a
        assert ctx.get_board("goal-b") is board_b

    def test_create_unified_board_property_raises(self) -> None:
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": _FakeBoard("goal-a"), "goal-b": _FakeBoard("goal-b")},
        )
        with pytest.raises(ValueError, match="Use get_board"):
            _ = ctx.board

    def test_create_unified_with_shared_agents(self) -> None:
        registry = MagicMock()
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a",),
            boards={"goal-a": _FakeBoard("goal-a")},
            shared_agents=registry,
        )
        assert ctx.shared_agents is registry

    def test_create_unified_with_budget(self) -> None:
        budget = MagicMock()
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a",),
            boards={"goal-a": _FakeBoard("goal-a")},
            budget=budget,
        )
        assert ctx.budget is budget


class TestFrozenDataclass:
    def test_execution_context_is_frozen(self) -> None:
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=_FakeBoard("goal-a"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.namespace = "modified"  # type: ignore[misc]

    def test_execution_context_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(ExecutionContext)


class TestScopedEventType:
    def test_isolated_mode_prefixes_event(self) -> None:
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=_FakeBoard("goal-a"),
        )
        assert ctx.scoped_event_type("task_completed") == "goal-a:task_completed"

    def test_unified_mode_passes_through(self) -> None:
        ctx = ExecutionContext.create_unified(
            namespaces=("goal-a", "goal-b"),
            boards={"goal-a": _FakeBoard("goal-a"), "goal-b": _FakeBoard("goal-b")},
        )
        assert ctx.scoped_event_type("task_completed") == "task_completed"


class TestGetBoardErrors:
    def test_get_board_unknown_namespace_raises_key_error(self) -> None:
        ctx = ExecutionContext.create_isolated(
            namespace="goal-a",
            board=_FakeBoard("goal-a"),
        )
        with pytest.raises(KeyError, match="No board for namespace"):
            ctx.get_board("nonexistent")
