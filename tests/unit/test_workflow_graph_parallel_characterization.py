"""Characterization: ``WorkflowGraph.add_parallel``/``execute`` state-merge semantics.

graph-composition spec, Task 3 (design-risk #2, design.md § Risks). Pins
the EXACT substrate facts ``harness/graph_assembly.py``'s per-node runner
design depends on, read directly off ``orchestration/workflow_graph.py``
(reuse-only -- this file is a NEW characterization test, it never edits the
substrate):

- ``execute()`` hands each parallel-group member a SHALLOW copy of state
  (``dict(state)``) -- a NEW top-level dict, but any NESTED mutable value
  (e.g. a nested ``dict``) is the SAME object reference across every
  member's copy. A member that MUTATES a nested dict in place makes that
  mutation visible to every sibling (and to the join node) -- nothing is
  lost. A member that REPLACES a nested dict wholesale (returns a new dict
  under the same key) only ever affects ITS OWN copy.
- After ``asyncio.gather`` resolves, results are merged back onto the
  outer ``state`` via ``for r in results: state.update(r)`` -- in
  ``group.node_ids`` DECLARATION order (the order passed to
  ``add_parallel``), NOT completion order. For any TOP-LEVEL key more than
  one member's result dict sets, the LAST-DECLARED member's value wins.
- Group entry: ``execute()`` treats ``current == entry_id`` (the synthetic
  id ``add_parallel`` derives, ``f"__parallel_{'_'.join(node_ids)}"``) as
  "run every member concurrently"; once every member has returned,
  ``current`` becomes ``group.then`` and execution proceeds from there.

Consequence this pins for the graph_assembly per-node runner design: a
node that wants EVERY sibling's output to survive a parallel fan-out MUST
mutate a shared nested dict (``state["outputs"][role] = text``) in place --
replacing it immutably would silently lose every sibling but the
last-declared one.
"""

from __future__ import annotations

import asyncio
from typing import Any

from swarmline.orchestration.workflow_graph import WorkflowGraph

State = dict[str, Any]


def _mutating_member(role: str) -> Any:
    """Member that MUTATES the shared nested ``outputs`` dict in place."""

    async def _run(state: State) -> State:
        state["outputs"][role] = f"{role}-out"
        return {**state, "last_role": role}

    return _run


def _replacing_member(role: str) -> Any:
    """Member that REPLACES ``outputs`` wholesale (no in-place mutation)."""

    async def _run(state: State) -> State:
        return {**state, "outputs": {role: f"{role}-out"}, "last_role": role}

    return _run


def _winner_member(role: str, *, delay: float = 0.0) -> Any:
    """Member that sets one top-level key (``winner``) -- delay proves the
    merge order is DECLARATION order, not completion order."""

    async def _run(state: State) -> State:
        if delay:
            await asyncio.sleep(delay)
        return {**state, "winner": role}

    return _run


async def _identity_join(state: State) -> State:
    return state


def _build_fanout_graph(member_builder: Any) -> WorkflowGraph:
    wf = WorkflowGraph("parallel-characterization")
    wf.add_node("r1", member_builder("r1"))
    wf.add_node("r2", member_builder("r2"))
    wf.add_node("r3", member_builder("r3"))
    wf.add_node("synth", _identity_join)
    wf.add_parallel(["r1", "r2", "r3"], then="synth")
    wf.set_entry("__parallel_r1_r2_r3")
    return wf


class TestParallelGroupSharesNestedStateAcrossMembers:
    """Members MUTATING a nested dict in place accumulate -- nothing lost."""

    async def test_in_place_mutation_of_nested_outputs_dict_accumulates_all_members(
        self,
    ) -> None:
        wf = _build_fanout_graph(_mutating_member)

        result = await wf.execute({"outputs": {}})

        assert result["outputs"] == {
            "r1": "r1-out",
            "r2": "r2-out",
            "r3": "r3-out",
        }

    async def test_join_node_after_group_sees_every_members_accumulated_output(
        self,
    ) -> None:
        """The synthetic entry_id -> every member -> ``then`` (synth) chain:
        current becomes ``group.then`` once all members finish, and synth
        observes the fully accumulated ``outputs`` (join-node contract the
        graph_assembly per-node runner relies on)."""
        captured: dict[str, Any] = {}

        async def _synth(state: State) -> State:
            captured["outputs_seen"] = dict(state["outputs"])
            return state

        wf = WorkflowGraph("parallel-characterization-join")
        wf.add_node("r1", _mutating_member("r1"))
        wf.add_node("r2", _mutating_member("r2"))
        wf.add_node("r3", _mutating_member("r3"))
        wf.add_node("synth", _synth)
        wf.add_parallel(["r1", "r2", "r3"], then="synth")
        wf.set_entry("__parallel_r1_r2_r3")

        await wf.execute({"outputs": {}})

        assert captured["outputs_seen"] == {
            "r1": "r1-out",
            "r2": "r2-out",
            "r3": "r3-out",
        }


class TestParallelGroupReplacingNestedStateLosesSiblings:
    """Members REPLACING a nested dict immutably each affect only their OWN
    shallow copy -- ``state.update(r)`` then lets the LAST-DECLARED member's
    replacement clobber every earlier one."""

    async def test_replacing_outputs_dict_wholesale_keeps_only_last_declared_member(
        self,
    ) -> None:
        wf = _build_fanout_graph(_replacing_member)

        result = await wf.execute({"outputs": {}})

        # r1/r2's writes are gone -- only "r3" (last in add_parallel's
        # node_ids order) survives the state.update() merge.
        assert result["outputs"] == {"r3": "r3-out"}


class TestParallelGroupTopLevelMergeUsesDeclarationOrder:
    """``for r in results: state.update(r)`` iterates in ``group.node_ids``
    DECLARATION order -- NOT completion order (asyncio.gather preserves the
    input list's order in its returned results, regardless of which
    awaitable actually finished first)."""

    async def test_last_declared_member_wins_a_shared_top_level_key_even_if_it_finishes_first(
        self,
    ) -> None:
        # r1 is slow (finishes LAST); r2/r3 are instant (finish FIRST).
        # If the merge were completion-order-based, "winner" would end up
        # "r2" or "r3". It is declaration-order-based, so "r3" (last in
        # add_parallel's node_ids list) always wins, regardless of timing.
        wf = WorkflowGraph("parallel-characterization-order")
        wf.add_node("r1", _winner_member("r1", delay=0.05))
        wf.add_node("r2", _winner_member("r2"))
        wf.add_node("r3", _winner_member("r3"))
        wf.add_node("synth", _identity_join)
        wf.add_parallel(["r1", "r2", "r3"], then="synth")
        wf.set_entry("__parallel_r1_r2_r3")

        result = await wf.execute({})

        assert result["winner"] == "r3"
