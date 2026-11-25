"""Fail-loud graph topology validation — REQ-010..014, REQ-019, REQ-020.

graph-composition spec, Task 2. :func:`validate_graph_topology` walks a
``CompositionSpec`` declared for ``mode="graph"`` and rejects every topology
mistake BEFORE any agent is built — every :class:`GraphTopologyError` names
the offending role/edge/route, never a bare "invalid topology".

Substrate facts this model is built on (``orchestration/workflow_graph.py``,
reuse-only, NOT imported here):

- ``add_parallel(node_ids, then)`` registers a group under a synthetic
  entry id; execution enters the group only when ``current == entry_id``,
  runs every member via ``asyncio.gather``, then continues from ``then``.
- ``_get_next``: a conditional edge (route) takes priority over a regular
  edge; a member's own outgoing regular edge is never consulted once the
  group has taken over — it would silently be dead code.
- A regular edge matches the FIRST edge by source (one successor).

Declarative topology -> normalized adjacency (v1 model, fixed order):

1. Edge ``(a, b)``: if ``b`` is a group member, rewrite to ``a -> G`` (the
   group's virtual node, meaning "enter the group as a whole"); dedup by
   target AFTER rewriting (two edges into two members of the SAME group
   collapse to one successor).
2. Group: ``G -> member`` for every member, ``member -> then`` for every
   member (``then`` itself rewritten through membership if it names another
   group's member).
3. Route ``(source, key, mapping, default)``: ``source -> target`` for
   every mapping value and the default, each rewritten through membership.
4. Entry = the FIRST declared worker; rewritten to its group's virtual node
   if it is a member.
5. Linear default (``edges == parallel == routes == ()``): a straight chain
   ``w1 -> w2 -> ... -> wN -> END``, validated through the same pipeline.

Checks run in this FIXED order (each raising a named
:class:`GraphTopologyError`): zero-workers, dup-role, tools-declared,
unknown-ref, dup-route-source, member-integrity, group-substrate-id-
collision, multi-successor, cycle, unreachable. REQ-018 (worker kernel
against the live kernel registry) is NOT duplicated here — it is already
enforced by ``builder.py``/``validation.py`` for every composition mode.

Node namespace (review r1 fix): a normalized graph node is either a
declared worker role (``str``) or a group's synthetic entry node
(``tuple[str, int]``, never equal to a ``str``) — no role collides with a
synthetic node IN THIS VALIDATOR's OWN model. The substrate derives a
PLAIN STRING id instead (``add_parallel``, ``workflow_graph.py:102``:
``f"__parallel_{'_'.join(members)}"``, same namespace as node ids) —
review r2: a role spelled like that string, or two groups whose members
join to the SAME string (``("a_b","c")``/``("a","b_c")`` both derive
``"__parallel_a_b_c"``), collide in the SUBSTRATE despite no conflict
above. :func:`_check_group_substrate_id_collisions` guards that.

Import-light (NFR-001): module scope carries only :mod:`swarmline.harness.spec`
and stdlib — no ``WorkflowGraph``/``ThinRuntime`` import, ever.
"""

from __future__ import annotations

from collections import deque
from typing import TypeAlias

from swarmline.harness.spec import (
    CompositionSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)

_END = "END"
_GROUP_TAG = "__group__"

#: A normalized graph node: a declared worker role (``str``) or a group's
#: synthetic entry node (``(tag, index)`` — structurally distinct from any
#: ``str``, so it can never collide with a user-chosen role name).
Node: TypeAlias = str | tuple[str, int]


class GraphTopologyError(ValueError):
    """A declared graph topology is invalid. The message always names the
    offending worker role, edge, route, or cycle."""


def validate_graph_topology(composition: CompositionSpec) -> None:
    """Validate *composition* (``mode="graph"``) end to end, or raise.

    Raises:
        GraphTopologyError: on the first violated check, in the fixed order
            documented in the module docstring.
    """
    roles = [worker.role for worker in composition.workers]
    _check_zero_workers(roles)
    role_set = _check_dup_role(roles)
    _check_tools_declared(composition.workers)
    _check_unknown_refs(composition, role_set)
    _check_dup_route_source(composition.routes)
    member_to_group = _check_member_integrity(composition)
    _check_group_substrate_id_collisions(composition, role_set)

    edges = _effective_edges(composition, roles)
    _check_multi_successor(edges, composition.routes, member_to_group)

    adjacency = _build_adjacency(composition, edges, member_to_group)
    nodes = _all_nodes(roles, composition.parallel)
    _check_cycle(adjacency, nodes, composition.parallel)

    entry = _entry_node(roles, member_to_group)
    _check_unreachable(adjacency, entry, roles)


def _check_zero_workers(roles: list[str]) -> None:
    if not roles:
        raise GraphTopologyError(
            "graph composition declares zero workers; add at least one WorkerSpec"
        )


def _check_dup_role(roles: list[str]) -> set[str]:
    seen: set[str] = set()
    for role in roles:
        if role in seen:
            raise GraphTopologyError(
                f"duplicate worker role {role!r} declared more than once; "
                "node identifiers must be unique"
            )
        seen.add(role)
    return seen


def _check_tools_declared(workers: tuple[WorkerSpec, ...]) -> None:
    for worker in workers:
        if worker.tools:
            raise GraphTopologyError(
                f"worker {worker.role!r} declares tools {worker.tools!r}; "
                "per-worker tool threading in graph mode is not yet "
                "supported (tracked follow-up)"
            )


def _check_unknown_refs(composition: CompositionSpec, role_set: set[str]) -> None:
    def _valid_target(name: str) -> bool:
        return name == _END or name in role_set

    for source, target in composition.edges:
        if source == _END:
            raise GraphTopologyError("'END' cannot be a source of an edge")
        if source not in role_set:
            raise GraphTopologyError(f"edge references unknown role {source!r}")
        if not _valid_target(target):
            raise GraphTopologyError(f"edge references unknown role {target!r}")

    for group in composition.parallel:
        for member in group.members:
            if member not in role_set:
                raise GraphTopologyError(
                    f"parallel group references unknown role {member!r}"
                )
        if not _valid_target(group.then):
            raise GraphTopologyError(
                f"parallel group references unknown role {group.then!r}"
            )

    for route in composition.routes:
        if route.source == _END:
            raise GraphTopologyError("'END' cannot be a source of a route")
        if route.source not in role_set:
            raise GraphTopologyError(f"route references unknown role {route.source!r}")
        for _value, target in route.mapping:
            if not _valid_target(target):
                raise GraphTopologyError(f"route references unknown role {target!r}")
        if route.default is not None and not _valid_target(route.default):
            raise GraphTopologyError(f"route references unknown role {route.default!r}")


def _check_dup_route_source(routes: tuple[RouteSpec, ...]) -> None:
    seen: set[str] = set()
    for route in routes:
        source = route.source
        if source in seen:
            raise GraphTopologyError(
                f"multiple routes declared from source {source!r}; a node "
                "may have at most one route"
            )
        seen.add(source)


def _check_member_integrity(composition: CompositionSpec) -> dict[str, int]:
    member_to_group: dict[str, int] = {}
    for group_index, group in enumerate(composition.parallel):
        for member in group.members:
            if member in member_to_group:
                raise GraphTopologyError(
                    f"worker {member!r} is a member of more than one "
                    "parallel group; membership must be exclusive"
                )
            member_to_group[member] = group_index

    for source, _target in composition.edges:
        if source in member_to_group:
            raise GraphTopologyError(
                f"worker {source!r} is a member of a parallel group; "
                "members converge to 'then'; declare downstream flow from "
                "the join node"
            )

    for route in composition.routes:
        if route.source in member_to_group:
            raise GraphTopologyError(
                f"worker {route.source!r} is a member of a parallel group; "
                "members converge to 'then'; declare downstream flow from "
                "the join node"
            )

    return member_to_group


def _substrate_group_id(members: tuple[str, ...]) -> str:
    """``WorkflowGraph.add_parallel``'s synthetic entry id
    (``workflow_graph.py:102``, reuse-only — mirrored, never imported)."""
    return f"__parallel_{'_'.join(members)}"


def _check_group_substrate_id_collisions(
    composition: CompositionSpec, role_set: set[str]
) -> None:
    """The two real substrate-namespace collisions review r2 flagged
    (module docstring "Node namespace"): a role spelled like a group's
    derived substrate id, or two groups deriving the SAME id."""
    seen_by_id: dict[str, ParallelSpec] = {}
    for group in composition.parallel:
        substrate_id = _substrate_group_id(group.members)
        if substrate_id in role_set:
            raise GraphTopologyError(
                f"worker role {substrate_id!r} collides with the synthetic "
                f"substrate id WorkflowGraph derives for parallel group "
                f"{group.members!r}; rename the role or the group's members"
            )
        other = seen_by_id.get(substrate_id)
        if other is not None:
            raise GraphTopologyError(
                f"parallel groups {other.members!r} and {group.members!r} "
                f"both derive the SAME substrate id {substrate_id!r}; "
                "rename members so the two groups don't collide"
            )
        seen_by_id[substrate_id] = group


def _group_node(index: int) -> Node:
    return (_GROUP_TAG, index)


def _normalize_target(name: str, member_to_group: dict[str, int]) -> Node:
    if name in member_to_group:
        return _group_node(member_to_group[name])
    return name


def _effective_edges(
    composition: CompositionSpec, roles: list[str]
) -> tuple[tuple[str, str], ...]:
    """Declared edges, or the REQ-005 linear default chain when the spec
    declares no topology at all (edges/parallel/routes all empty)."""
    if composition.edges or composition.parallel or composition.routes:
        return composition.edges
    chain = tuple(zip(roles, roles[1:]))
    return chain + ((roles[-1], _END),)


def _check_multi_successor(
    edges: tuple[tuple[str, str], ...],
    routes: tuple[RouteSpec, ...],
    member_to_group: dict[str, int],
) -> None:
    targets_by_source: dict[str, set[Node]] = {}
    for source, target in edges:
        targets_by_source.setdefault(source, set()).add(
            _normalize_target(target, member_to_group)
        )

    route_sources = {route.source for route in routes}

    for source, targets in targets_by_source.items():
        if len(targets) > 1:
            raise GraphTopologyError(
                f"worker {source!r} declares more than one unconditional "
                "outgoing edge; use a parallel group or a route instead"
            )
        if source in route_sources:
            raise GraphTopologyError(
                f"worker {source!r} declares both an unconditional edge and "
                "a route; use a parallel group or a route instead"
            )


def _build_adjacency(
    composition: CompositionSpec,
    edges: tuple[tuple[str, str], ...],
    member_to_group: dict[str, int],
) -> dict[Node, set[Node]]:
    adjacency: dict[Node, set[Node]] = {}

    def _add(source: Node, target: Node) -> None:
        adjacency.setdefault(source, set()).add(target)

    for source, target in edges:
        _add(source, _normalize_target(target, member_to_group))

    for group_index, group in enumerate(composition.parallel):
        gnode = _group_node(group_index)
        then_target = _normalize_target(group.then, member_to_group)
        for member in group.members:
            _add(gnode, member)
            _add(member, then_target)

    for route in composition.routes:
        targets = {value_target for _key, value_target in route.mapping}
        if route.default is not None:
            targets.add(route.default)
        for target in targets:
            _add(route.source, _normalize_target(target, member_to_group))

    return adjacency


def _all_nodes(roles: list[str], parallel: tuple[ParallelSpec, ...]) -> set[Node]:
    nodes: set[Node] = set(roles)
    nodes.update(_group_node(i) for i in range(len(parallel)))
    return nodes


def _entry_node(roles: list[str], member_to_group: dict[str, int]) -> Node:
    entry = roles[0]
    if entry in member_to_group:
        return _group_node(member_to_group[entry])
    return entry


def _sort_key(node: Node) -> tuple[int, str, int]:
    """Deterministic, cross-type-safe sort key (``str`` and ``tuple`` nodes
    can't be compared with plain ``<``)."""
    if isinstance(node, tuple):
        return (1, node[0], node[1])
    return (0, node, 0)


def _display_name(node: Node, parallel: tuple[ParallelSpec, ...]) -> str:
    if isinstance(node, tuple):
        _tag, index = node
        members = ", ".join(parallel[index].members)
        return f"parallel-group({members})"
    return node


def _check_cycle(
    adjacency: dict[Node, set[Node]],
    nodes: set[Node],
    parallel: tuple[ParallelSpec, ...],
) -> None:
    white, gray, black = 0, 1, 2
    color: dict[Node, int] = dict.fromkeys(nodes, white)
    path: list[Node] = []

    def visit(node: Node) -> None:
        color[node] = gray
        path.append(node)
        for target in sorted(adjacency.get(node, ()), key=_sort_key):
            if target == _END or target not in color:
                continue
            if color[target] == gray:
                cycle_start = path.index(target)
                cycle_nodes = [*path[cycle_start:], target]
                names = " -> ".join(_display_name(n, parallel) for n in cycle_nodes)
                raise GraphTopologyError(f"cycle detected: {names}")
            if color[target] == white:
                visit(target)
        path.pop()
        color[node] = black

    for node in sorted(nodes, key=_sort_key):
        if color[node] == white:
            visit(node)


def _check_unreachable(
    adjacency: dict[Node, set[Node]], entry: Node, roles: list[str]
) -> None:
    visited: set[Node] = {entry}
    queue: deque[Node] = deque([entry])
    while queue:
        node = queue.popleft()
        for target in adjacency.get(node, ()):
            if target == _END or target in visited:
                continue
            visited.add(target)
            queue.append(target)

    for role in roles:
        if role not in visited:
            raise GraphTopologyError(
                f"worker {role!r} is unreachable from the entry node"
            )
