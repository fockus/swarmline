"""Deterministic validation layer (pre-deploy, layer 1) for autopilot blueprints.

TDD Task 2 of the autopilot-orchestrator spec (Epic G). Covers REQ-005, REQ-022.
Reuses the real `multi_agent.graph_governance` checks via lightweight attribute
adapters — no re-implementation of subset/delegation logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from swarmline.multi_agent.graph_governance import (
    GraphGovernanceConfig,
    check_delegate_allowed,
    validate_capability_delegation,
)
from swarmline.orchestration.autopilot.types import (
    OrchestrationBlueprint,
    OutputContract,
)

_VALID_CRITERION_KINDS = ("deterministic", "subjective")


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Coerce an optional list/tuple field to a tuple; anything else -> ().

    Keeps the deterministic validator crash-proof: a generated blueprint may
    emit ``null`` (or a wrong type) for ``allowed_tools``/``skills``/``hooks``.
    """
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def validate_blueprint(
    blueprint: OrchestrationBlueprint,
    *,
    governance: GraphGovernanceConfig,
    graph_schema: Callable[[dict], tuple[str, ...]] | None = None,
) -> tuple[str, ...]:
    """Validate a blueprint deterministically. Returns all problems found.

    Empty tuple = valid. Never early-returns — collects every problem so a
    single pass surfaces the full picture (structure, governance limits,
    capability subsets, assignee existence, contract well-formedness).
    """
    problems: list[str] = []
    node_ids: set[str] = set()

    # 1. Graph-schema validity (+ collect node ids / count / max depth below).
    if graph_schema is not None:
        problems.extend(graph_schema(blueprint.graph))
        max_depth, node_count = _walk_graph(
            blueprint.graph, 1, node_ids, [], emit_problems=False
        )
    else:
        max_depth, node_count = _walk_graph(
            blueprint.graph, 1, node_ids, problems, emit_problems=True
        )

    # 2. Governance limits (count TOTAL node instances, not unique ids).
    if node_count > governance.max_agents:
        problems.append(
            f"Graph has {node_count} agents, exceeding max_agents "
            f"({governance.max_agents})"
        )
    if max_depth > governance.max_depth:
        problems.append(
            f"Graph depth {max_depth} exceeds max_depth ({governance.max_depth})"
        )

    # 3. Capability subset + delegate-allowed (reuses real governance checks).
    _check_capabilities(blueprint.graph, governance, problems)

    # 4. Assignee existence.
    for task in blueprint.tasks:
        if task.assignee_node_id not in node_ids:
            problems.append(
                f"Task '{task.id}' assigned to unknown node '{task.assignee_node_id}'"
            )

    # 5. Contract well-formedness.
    _check_contract(blueprint.contract, problems)

    return tuple(problems)


def _walk_graph(
    node: Any,
    depth: int,
    seen_ids: set[str],
    problems: list[str],
    *,
    emit_problems: bool,
) -> tuple[int, int]:
    """Recurse the nested-dict graph, collecting node ids, count, max depth.

    Returns ``(max_depth, total_node_count)``. When `emit_problems` is True,
    also runs the built-in structural check (non-empty id/name/role,
    list-typed children, unique ids).
    """
    if not isinstance(node, dict):
        if emit_problems:
            problems.append("Graph node is not a dict")
        return depth, 0

    node_id = node.get("id")
    node_label = node_id or "<unknown>"
    if emit_problems:
        if not node_id:
            problems.append("Graph node missing non-empty 'id'")
        if not node.get("name"):
            problems.append(f"Graph node '{node_label}' missing non-empty 'name'")
        if not node.get("role"):
            problems.append(f"Graph node '{node_label}' missing non-empty 'role'")

    if node_id:
        if emit_problems and node_id in seen_ids:
            problems.append(f"Duplicate node id '{node_id}' in graph")
        seen_ids.add(node_id)

    children = node.get("children", [])
    if not isinstance(children, list):
        if emit_problems:
            problems.append(f"Graph node '{node_label}' has non-list 'children'")
        children = []

    max_depth = depth
    total = 1
    for child in children:
        child_depth, child_total = _walk_graph(
            child, depth + 1, seen_ids, problems, emit_problems=emit_problems
        )
        max_depth = max(max_depth, child_depth)
        total += child_total
    return max_depth, total


def _check_capabilities(
    node: Any, governance: GraphGovernanceConfig, problems: list[str]
) -> None:
    """Recurse the graph, calling the REAL governance functions on adapters.

    For every parent with children: `check_delegate_allowed` (governance).
    For every parent->child edge: `validate_capability_delegation` (subset).
    """
    if not isinstance(node, dict):
        return

    children = node.get("children", [])
    if not isinstance(children, list):
        return

    node_name = node.get("name", node.get("id", ""))

    if children:
        caps = node.get("capabilities")
        can_delegate = (
            caps.get("can_delegate", True) if isinstance(caps, dict) else True
        )
        node_adapter = SimpleNamespace(
            name=node_name,
            capabilities=SimpleNamespace(can_delegate=can_delegate),
        )
        delegate_problem = check_delegate_allowed(governance, node_adapter)
        if delegate_problem:
            problems.append(delegate_problem)

    parent_adapter = SimpleNamespace(
        name=node_name,
        allowed_tools=_as_tuple(node.get("allowed_tools")),
        skills=_as_tuple(node.get("skills")),
        hooks=_as_tuple(node.get("hooks")),
    )
    for child in children:
        if not isinstance(child, dict):
            continue
        subset_problem = validate_capability_delegation(
            parent_adapter,
            _as_tuple(child.get("allowed_tools")),
            _as_tuple(child.get("skills")),
            _as_tuple(child.get("hooks")),
        )
        if subset_problem:
            problems.append(subset_problem)
        _check_capabilities(child, governance, problems)


def _check_contract(contract: OutputContract, problems: list[str]) -> None:
    """Flag criteria with empty verifiers or an unrecognised `kind`.

    Deliverables are allowed to be empty — that is not flagged.
    """
    for criterion in contract.criteria:
        if not criterion.verifier:
            problems.append(f"Criterion '{criterion.id}' has an empty verifier")
        if criterion.kind not in _VALID_CRITERION_KINDS:
            problems.append(
                f"Criterion '{criterion.id}' has invalid kind '{criterion.kind}'"
            )
