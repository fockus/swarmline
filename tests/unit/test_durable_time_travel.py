"""TDD tests for Stage C1.3 — time-travel (``get_state_history`` + ``fork``).

Pure wrappers over a B1 ``Checkpointer`` (``InMemoryCheckpointer``) — zero new
dependencies, zero vendor SDKs. Covers the 5 plan-mandated tests plus edge
cases (fork of a ``running`` checkpoint; two forks from the same source;
mixed-status history returned fully).
"""

from __future__ import annotations

import pytest

from swarmline.durable import fork, get_state_history
from swarmline.session import InMemoryCheckpointer

# ---------------------------------------------------------------------------
# Plan-mandated tests (5)
# ---------------------------------------------------------------------------


async def test_get_state_history_returns_checkpoints_oldest_first() -> None:
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put("t1", {"status": "running", "step": 1})
    cp2 = await checkpointer.put("t1", {"status": "running", "step": 2}, parent_id=cp1)
    cp3 = await checkpointer.put("t1", {"status": "done"}, parent_id=cp2)

    history = await get_state_history(checkpointer, "t1")

    assert [cp.id for cp in history] == [cp1, cp2, cp3]
    ts_values = [cp.ts for cp in history]
    assert ts_values == sorted(ts_values)
    assert history[1].parent_id == cp1
    assert history[2].parent_id == cp2


async def test_get_state_history_empty_thread_returns_empty() -> None:
    checkpointer = InMemoryCheckpointer()
    assert await get_state_history(checkpointer, "unknown") == []


async def test_fork_creates_new_checkpoint_with_parent_lineage() -> None:
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put("t1", {"status": "done", "messages": []})

    new_id = await fork(checkpointer, "t1", cp1)

    assert new_id != cp1
    forked = await checkpointer.get("t1", checkpoint_id=new_id)
    assert forked is not None
    assert forked.parent_id == cp1
    original = await checkpointer.get("t1", checkpoint_id=cp1)
    assert original is not None
    assert forked.state == original.state


async def test_fork_missing_checkpoint_raises_lookup_error() -> None:
    checkpointer = InMemoryCheckpointer()
    with pytest.raises(LookupError, match="missing-id"):
        await fork(checkpointer, "t1", "missing-id")


async def test_fork_diverges_independent_timeline() -> None:
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put("t1", {"status": "done"})
    cp2 = await checkpointer.put("t1", {"status": "done", "n": 2}, parent_id=cp1)

    fork_id = await fork(checkpointer, "t1", cp1)
    # Write onto the forked branch.
    fork_child = await checkpointer.put(
        "t1", {"status": "done", "branch": "fork"}, parent_id=fork_id
    )

    # Original lineage untouched: cp2 still parents off cp1.
    original_cp2 = await checkpointer.get("t1", checkpoint_id=cp2)
    assert original_cp2 is not None
    assert original_cp2.parent_id == cp1

    fork_child_cp = await checkpointer.get("t1", checkpoint_id=fork_child)
    assert fork_child_cp is not None
    assert fork_child_cp.parent_id == fork_id
    # The fork's child is not reachable from the original cp2 chain.
    assert fork_child != cp2


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C1.3)
# ---------------------------------------------------------------------------


async def test_fork_of_running_checkpoint_is_allowed() -> None:
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put("t1", {"status": "running", "step": 1})

    new_id = await fork(checkpointer, "t1", cp1)

    forked = await checkpointer.get("t1", checkpoint_id=new_id)
    assert forked is not None
    assert forked.parent_id == cp1
    assert forked.state["status"] == "running"


async def test_fork_twice_from_same_checkpoint_creates_sibling_branches() -> None:
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put("t1", {"status": "done"})

    branch_a = await fork(checkpointer, "t1", cp1)
    branch_b = await fork(checkpointer, "t1", cp1)

    assert branch_a != branch_b
    cp_a = await checkpointer.get("t1", checkpoint_id=branch_a)
    cp_b = await checkpointer.get("t1", checkpoint_id=branch_b)
    assert cp_a is not None and cp_b is not None
    assert cp_a.parent_id == cp1
    assert cp_b.parent_id == cp1


async def test_get_state_history_returns_mixed_status_checkpoints() -> None:
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put("t1", {"status": "running"})
    await checkpointer.put("t1", {"status": "done"})
    await checkpointer.put("t1", {"status": "running"})

    history = await get_state_history(checkpointer, "t1")

    assert [cp.state["status"] for cp in history] == ["running", "done", "running"]


# ---------------------------------------------------------------------------
# Fix-cycle r1 — adversarial review MAJORs
# ---------------------------------------------------------------------------


async def test_get_state_history_with_duplicate_checkpoint_id_fails_loud() -> None:
    """B1's ``Checkpointer`` explicitly allows an explicit duplicate
    ``checkpoint_id`` to append a new row rather than replace one, and
    ``get(checkpoint_id=...)`` returns only the LATEST matching row -- so a
    naive ``list()`` + per-id ``get()`` would silently collapse the earlier
    row(s) under a duplicated id. That is not an honest "full history"; fail
    loud instead of lying."""
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put("t1", {"status": "running", "step": 1}, checkpoint_id="same")
    await checkpointer.put("t1", {"status": "done", "step": 2}, checkpoint_id="same")

    with pytest.raises(ValueError, match="same"):
        await get_state_history(checkpointer, "t1")


async def test_fork_does_not_alias_nested_state_with_source() -> None:
    """``fork``'s own contract promises an independent timeline. Both
    ``InMemoryCheckpointer.get`` and ``.put`` only shallow-copy ``state``, so
    passing the source's ``state`` straight into ``put`` would leave nested
    containers (e.g. a ``messages`` list) shared between source and fork --
    mutating one would mutate the other."""
    checkpointer = InMemoryCheckpointer()
    cp1 = await checkpointer.put(
        "t1", {"messages": [{"role": "user"}], "items": [1, 2]}
    )

    fork_id = await fork(checkpointer, "t1", cp1)

    forked = await checkpointer.get("t1", checkpoint_id=fork_id)
    assert forked is not None
    forked.state["items"].append(999)  # mutate the FORK's nested state

    source = await checkpointer.get("t1", checkpoint_id=cp1)
    assert source is not None
    assert source.state["items"] == [1, 2]  # source untouched
