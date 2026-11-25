"""Domain value types for the autopilot orchestrator (Epic G).

Blueprint, Contract, Result, Config value types for the generative meta-loop
(plan -> verify -> deploy -> gate) layered over the closed H6 supervisor.
All types are frozen dataclasses. Zero external dependencies — stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OrchestrationPhase(Enum):
    """Phases of the autopilot meta-loop."""

    PLAN = "plan"
    VERIFY = "verify"
    APPROVAL = "approval"
    DEPLOY = "deploy"
    GATE = "gate"
    REPAIR = "repair"
    DONE = "done"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """A single criterion the contract gate checks artifacts against."""

    id: str
    description: str
    kind: Literal["deterministic", "subjective"]
    verifier: str


@dataclass(frozen=True)
class OutputContract:
    """Deliverables + acceptance criteria a blueprint run must satisfy."""

    deliverables: tuple[str, ...]
    criteria: tuple[AcceptanceCriterion, ...]
    output_schema: dict | None = None
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlueprintTask:
    """A single task assigned to a graph node within a blueprint.

    # AgentGoal (multi_agent/agent_goal.py) is F1-deferred and absent from the
    # tree; `goal` is the current `str` representation (goal text/prompt).
    """

    id: str
    title: str
    assignee_node_id: str
    goal: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrchestrationBlueprint:
    """Generated (or hardcoded) blueprint: graph + tasks + output contract."""

    graph: dict
    tasks: tuple[BlueprintTask, ...]
    contract: OutputContract
    rationale: str = ""


@dataclass(frozen=True)
class GateVerdict:
    """Result of the contract gate evaluating deployed artifacts."""

    passed: bool
    failures: tuple[str, ...] = ()
    log: str = ""


@dataclass(frozen=True)
class CriticVerdict:
    """Result of the LLM critic reviewing a blueprint before deploy."""

    passed: bool
    failures: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class OrchestratorConfig:
    """Repair budgets and gating flags for an orchestrator run."""

    max_plan_repair: int = 3
    max_gate_repair: int = 3
    require_plan_approval: bool = False
    max_recursion_depth: int = 2
    verifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrchestrationResult:
    """Final result of an autopilot orchestrator run."""

    status: str
    blueprint: OrchestrationBlueprint | None
    contract: OutputContract | None
    verdict: GateVerdict | None
    phase_log: tuple[str, ...] = ()
    board_snapshot: dict | None = None
