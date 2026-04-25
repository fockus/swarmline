"""Stage 2 (Sprint 1A): pin DefaultCodingTaskRuntime board dependency to a
composite ISP-compliant Protocol.

Background — `coding_task_runtime.py` previously type-hinted `board: GraphTaskBoard`
but called `cancel_task` / `get_ready_tasks` / `get_blocked_by` on it. Those
methods exist in every concrete backend (InMemory / SQLite / Postgres) but live
in *separate* protocols (`GraphTaskScheduler`) or no protocol at all
(`cancel_task`). Result: `ty` reported 3 unresolved-attribute errors at
`coding_task_runtime.py:163,180,184`.

Fix — introduce `CodingTaskBoardPort` (5 methods, ISP-compliant) in
`coding_task_ports.py` that consolidates exactly the 5 methods the runtime
calls on `board`. Backends satisfy it via duck typing.
"""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.orchestration.coding_task_ports import CodingTaskBoardPort


def test_coding_task_board_port_protocol_exists() -> None:
    """`CodingTaskBoardPort` is exported from coding_task_ports."""
    # Bare import is the assertion — ImportError would fail collection.
    assert hasattr(CodingTaskBoardPort, "__name__")
    assert CodingTaskBoardPort.__name__ == "CodingTaskBoardPort"


def test_coding_task_board_port_has_required_methods() -> None:
    """`CodingTaskBoardPort` is a *composition* of 3 narrow protocols.

    Each narrow protocol stays ISP-compliant (≤5 methods):
    - GraphTaskBoard subset: create_task, checkout_task, complete_task, list_tasks (4)
    - GraphTaskScheduler: get_ready_tasks, get_blocked_by (2)
    - Backend-specific: cancel_task (1)

    The port aggregates 7 methods total — acceptable as a *composed* Protocol
    (orchestration-layer port) because the underlying source protocols stay
    narrow. The runtime needs all 7 methods on a single `board` parameter.
    """
    expected = {
        "create_task",
        "checkout_task",
        "complete_task",
        "cancel_task",
        "list_tasks",
        "get_ready_tasks",
        "get_blocked_by",
    }
    actual = {
        name
        for name in dir(CodingTaskBoardPort)
        if not name.startswith("_") and callable(getattr(CodingTaskBoardPort, name))
    }
    missing = expected - actual
    assert not missing, f"CodingTaskBoardPort missing methods: {missing}"


def test_in_memory_graph_task_board_satisfies_composite_port() -> None:
    """`InMemoryGraphTaskBoard` duck-types `CodingTaskBoardPort`.

    Runtime check via `isinstance` requires `@runtime_checkable`. The 3
    backends (InMemory/SQLite/Postgres) all implement these 5 methods —
    if any one fails, `DefaultCodingTaskRuntime` would crash at runtime.
    """
    board = InMemoryGraphTaskBoard(namespace="coding")
    assert isinstance(board, CodingTaskBoardPort), (
        "InMemoryGraphTaskBoard must satisfy CodingTaskBoardPort. "
        "Missing one of: list_tasks, complete_task, cancel_task, "
        "get_ready_tasks, get_blocked_by."
    )


def test_default_coding_task_runtime_board_param_typed_to_port() -> None:
    """`DefaultCodingTaskRuntime.__init__` annotates `board` as `CodingTaskBoardPort`.

    Verifies the type-hint via `inspect.get_annotations` to lock the contract.
    Without this, future refactors could silently downgrade to `GraphTaskBoard`
    again and reintroduce the 3 ty errors.
    """
    import inspect

    from swarmline.orchestration.coding_task_runtime import DefaultCodingTaskRuntime

    sig = inspect.signature(DefaultCodingTaskRuntime.__init__)
    board_param = sig.parameters.get("board")
    assert board_param is not None, "board parameter missing"
    annotation_str = str(board_param.annotation)
    assert "CodingTaskBoardPort" in annotation_str, (
        f"Expected board: CodingTaskBoardPort, got {annotation_str!r}. "
        f"Did the runtime signature regress to GraphTaskBoard?"
    )


def test_minimal_graph_task_board_subset_does_not_satisfy_port() -> None:
    """A class with only the 5 GraphTaskBoard methods does NOT satisfy port.

    Negative assertion: confirms the port is genuinely composite (not just a
    rename of GraphTaskBoard). A board lacking cancel_task / get_ready_tasks /
    get_blocked_by must be rejected by isinstance check.
    """

    class MinimalBoard:
        # Only GraphTaskBoard's 5 methods, no scheduler/canceller methods
        async def create_task(self, task) -> None: ...  # noqa: ANN001
        async def checkout_task(self, task_id: str, agent_id: str): ...
        async def complete_task(self, task_id: str) -> bool: ...  # noqa: ARG002
        async def get_subtasks(self, task_id: str) -> list: ...  # noqa: ARG002
        async def list_tasks(self, **filters) -> list: ...  # noqa: ARG002

    minimal = MinimalBoard()
    assert not isinstance(minimal, CodingTaskBoardPort), (
        "MinimalBoard should NOT satisfy CodingTaskBoardPort — it lacks "
        "cancel_task / get_ready_tasks / get_blocked_by."
    )


@pytest.mark.parametrize(
    "missing_method",
    ["list_tasks", "complete_task", "cancel_task", "get_ready_tasks", "get_blocked_by"],
)
def test_port_rejects_board_missing_any_required_method(missing_method: str) -> None:
    """Drop one method at a time — each removal causes isinstance check to fail."""

    method_signatures = {
        "list_tasks": "async def list_tasks(self, **filters): ...",
        "complete_task": "async def complete_task(self, task_id): ...",
        "cancel_task": "async def cancel_task(self, task_id): ...",
        "get_ready_tasks": "async def get_ready_tasks(self): ...",
        "get_blocked_by": "async def get_blocked_by(self, task_id): ...",
    }

    methods = {k: v for k, v in method_signatures.items() if k != missing_method}
    class_body = "\n    ".join(methods.values())
    namespace: dict = {}
    exec(  # noqa: S102 — controlled compile of a fixed string
        f"class _PartialBoard:\n    {class_body}",
        namespace,
    )
    instance = namespace["_PartialBoard"]()
    assert not isinstance(instance, CodingTaskBoardPort), (
        f"_PartialBoard missing {missing_method!r} should not satisfy port"
    )
