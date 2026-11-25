"""Regression: virtual parallel-group node namespace collisions (review
r1 major -- validator's OWN model; review r2 major -- the SUBSTRATE's).

graph-composition spec, Task 2 fix (r1). Before this fix, ``graph_validation.py``
encoded a parallel group's synthetic entry node as a PLAIN STRING
(``f"__graph_validation_group_{i}"``) sharing the same namespace as
user-declared worker roles (unbounded strings). Two observable defects:

1. A role literally named like the reserved prefix, involved in a cycle,
   made ``_display_name`` misinterpret it as a real synthetic group
   reference and crash with a raw ``IndexError`` (``parallel[index]`` out
   of range) instead of raising ``GraphTopologyError``.
2. A role literally equal to an ACTUAL group's synthetic id string collided
   with that group's virtual entry node in the node/adjacency sets — BFS
   reachability then silently treated the (genuinely disconnected) role as
   reachable through the unrelated parallel group's traversal.

Fix: virtual group nodes are now ``tuple[str, int]`` — structurally never
equal to any ``str`` role name, so no user-chosen role string can collide
with a synthetic node, regardless of its literal spelling, IN THE
VALIDATOR'S OWN MODEL.

graph-composition Task 3 fix (r2). That tuple tag never reaches the
SUBSTRATE, though: ``WorkflowGraph.add_parallel`` (``workflow_graph.py:102``)
derives a PLAIN STRING id (``f"__parallel_{'_'.join(members)}"``) and
stores it in the SAME namespace as regular node ids. Two real substrate-
level collisions ``_check_group_substrate_id_collisions`` now rejects:
(a) a worker role literally spelled like a group's derived id (the group
would shadow that role at run time); (b) two DIFFERENT groups whose
members join to the SAME string (e.g. ``("a_b", "c")`` and
``("a", "b_c")`` both derive ``"__parallel_a_b_c"``) -- the later
``add_parallel`` call would silently overwrite the earlier one.
"""

from __future__ import annotations

import pytest

from swarmline.harness.graph_validation import (
    GraphTopologyError,
    validate_graph_topology,
)
from swarmline.harness.spec import CompositionSpec, ParallelSpec, WorkerSpec

_RESERVED_LOOKALIKE = "__graph_validation_group_0"


def _workers(*roles: str) -> tuple[WorkerSpec, ...]:
    return tuple(WorkerSpec(role=role) for role in roles)


class TestReservedLookalikeRoleNameNeverCollidesWithVirtualGroupNode:
    """A worker role that happens to spell out the (former) internal
    virtual-node naming scheme is just an ordinary role — never a synthetic
    node — no matter what parallel groups exist alongside it."""

    def test_self_cycle_on_reserved_lookalike_role_raises_graph_topology_error(
        self,
    ) -> None:
        """Defect 1: self-edge on a reserved-lookalike role used to crash
        ``_display_name`` with a raw ``IndexError`` (no parallel groups
        declared at all, so ``parallel[0]`` was out of range)."""
        composition = CompositionSpec(
            mode="graph",
            workers=_workers(_RESERVED_LOOKALIKE, "other"),
            edges=((_RESERVED_LOOKALIKE, _RESERVED_LOOKALIKE),),
        )

        with pytest.raises(GraphTopologyError, match=_RESERVED_LOOKALIKE):
            validate_graph_topology(composition)

    def test_disconnected_reserved_lookalike_role_is_reported_unreachable(
        self,
    ) -> None:
        """Defect 2: with a REAL parallel group at index 0, a disconnected
        role literally named after that group's (former) synthetic id used
        to be silently swept up as "reachable" by the string collision —
        it must be reported unreachable, since nothing actually points at
        it."""
        composition = CompositionSpec(
            mode="graph",
            workers=_workers("entry", "r1", "r2", "synth", _RESERVED_LOOKALIKE),
            edges=(("entry", "r1"),),
            parallel=(ParallelSpec(members=("r1", "r2"), then="synth"),),
        )

        with pytest.raises(GraphTopologyError, match=_RESERVED_LOOKALIKE):
            validate_graph_topology(composition)

    def test_reserved_lookalike_role_with_real_edges_still_validates_fine(
        self,
    ) -> None:
        """Non-regression: a reserved-lookalike role that IS properly wired
        into the topology passes like any other role would."""
        composition = CompositionSpec(
            mode="graph",
            workers=_workers("entry", _RESERVED_LOOKALIKE),
            edges=(("entry", _RESERVED_LOOKALIKE), (_RESERVED_LOOKALIKE, "END")),
        )

        assert validate_graph_topology(composition) is None


class TestGroupSubstrateIdCollisionsAreRejected:
    """Review r2 major: the SUBSTRATE's own plain-string synthetic id
    (``f"__parallel_{'_'.join(members)}"``, ``workflow_graph.py:102``) can
    collide even where the validator's tuple-tagged model above sees no
    conflict at all."""

    def test_role_spelled_like_a_groups_derived_substrate_id_raises(self) -> None:
        """(a) A role literally equal to a group's derived substrate id
        would be shadowed by that group at run time -- rejected instead of
        silently misrouting."""
        reserved = "__parallel_a_b"
        composition = CompositionSpec(
            mode="graph",
            workers=_workers("a", "b", reserved),
            parallel=(ParallelSpec(members=("a", "b"), then=reserved),),
        )

        with pytest.raises(GraphTopologyError, match=reserved):
            validate_graph_topology(composition)

    def test_two_groups_deriving_the_same_substrate_id_raises_naming_both(
        self,
    ) -> None:
        """(b) Two DIFFERENT groups whose members join to the SAME string
        (``("a_b", "c")`` and ``("a", "b_c")`` both derive
        ``"__parallel_a_b_c"``) -- the later ``add_parallel`` would
        silently overwrite the earlier one's registration."""
        composition = CompositionSpec(
            mode="graph",
            workers=_workers("a_b", "c", "a", "b_c", "join1", "join2"),
            parallel=(
                ParallelSpec(members=("a_b", "c"), then="join1"),
                ParallelSpec(members=("a", "b_c"), then="join2"),
            ),
        )

        with pytest.raises(GraphTopologyError) as exc_info:
            validate_graph_topology(composition)

        message = str(exc_info.value)
        assert "__parallel_a_b_c" in message
        assert "('a_b', 'c')" in message
        assert "('a', 'b_c')" in message

    def test_two_groups_with_non_colliding_substrate_ids_validate_fine(
        self,
    ) -> None:
        """Control: distinct member tuples deriving distinct substrate ids
        (and reachable end to end) validate cleanly -- the new check does
        not reject valid multi-group topologies."""
        composition = CompositionSpec(
            mode="graph",
            workers=_workers("a", "b", "join1", "c", "d", "join2"),
            edges=(("join1", "c"), ("join2", "END")),
            parallel=(
                ParallelSpec(members=("a", "b"), then="join1"),
                ParallelSpec(members=("c", "d"), then="join2"),
            ),
        )

        assert validate_graph_topology(composition) is None
