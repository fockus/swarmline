"""swarmline.pipeline — universal pipeline layer for agent graph orchestration.

Provides phase-based execution with quality gates, budget tracking,
circuit breakers, and a fluent builder API.

Quick start::

    from swarmline.pipeline import PipelineBuilder, BudgetPolicy

    pipeline = await (
        PipelineBuilder()
        .with_agents_from_yaml("org.yaml")
        .with_runner(my_llm_runner)
        .add_phase("plan", "Planning", "Decompose the goal into tasks")
        .add_phase("exec", "Execution", "Execute all planned tasks")
        .with_budget(BudgetPolicy(max_total_usd=10.0))
        .build()
    )
    result = await pipeline.run("Build a REST API")
"""

from swarmline.pipeline.budget import BudgetExceededError, BudgetTracker
from swarmline.pipeline.budget_store import (
    InMemoryPersistentBudgetStore,
    PersistentBudgetStore,
    SqlitePersistentBudgetStore,
)
from swarmline.pipeline.budget_types import (
    BudgetIncident,
    BudgetScope,
    BudgetScopeType,
    BudgetThreshold,
    BudgetWindow,
    CostEvent,
    ThresholdAction,
    ThresholdResult,
)
from swarmline.pipeline.builder import PipelineBuilder
from swarmline.pipeline.gate import CallbackGate, CompositeGate
from swarmline.pipeline.pipeline import Pipeline
from swarmline.pipeline.protocols import CostTracker, GoalDecomposer, QualityGate
from swarmline.pipeline.runner import PipelineRunner
from swarmline.pipeline.types import (
    BudgetPolicy,
    CostRecord,
    GateResult,
    Goal,
    PhaseResult,
    PhaseStatus,
    PipelinePhase,
    PipelineResult,
)

__all__ = [
    "BudgetExceededError",
    "BudgetIncident",
    "BudgetPolicy",
    "BudgetScope",
    "BudgetScopeType",
    "BudgetThreshold",
    "BudgetTracker",
    "BudgetWindow",
    "CallbackGate",
    "CompositeGate",
    "CostEvent",
    "CostRecord",
    "CostTracker",
    "GateResult",
    "Goal",
    "GoalDecomposer",
    "InMemoryPersistentBudgetStore",
    "PersistentBudgetStore",
    "PhaseResult",
    "PhaseStatus",
    "Pipeline",
    "PipelineBuilder",
    "PipelinePhase",
    "PipelineResult",
    "PipelineRunner",
    "QualityGate",
    "SqlitePersistentBudgetStore",
    "ThresholdAction",
    "ThresholdResult",
]
