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
from swarmline.pipeline.bridge import WorkflowBridge
from swarmline.pipeline.gate import CallbackGate, CompositeGate
from swarmline.pipeline.pipeline import Pipeline
from swarmline.pipeline.protocols import CostTracker, GoalDecomposer, QualityGate
from swarmline.pipeline.runner import PipelineRunner
# The deprecated long stage aliases (TypedPipelineStage / ParallelPipelineStage / LoopPipelineStage)
# are intentionally NOT imported eagerly and NOT listed in ``__all__`` — they are served lazily by
# ``__getattr__`` below so that ``import swarmline.pipeline`` and ``from swarmline.pipeline import *``
# stay warning-free (under ``-W error`` too). They remain importable by explicit name (which warns).
from swarmline.pipeline.typed import (
    FallbackPolicy,
    PipelineContext,
    TypedPipeline,
    TypedPipelineResult,
    WorkflowChain,
    WorkflowChainResult,
    WorkflowStep,
)
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

# ── Typed data-flow pipeline (registry-dispatch substrate, additive) ────────────────────
# A declarative, registry-dispatch pipeline layer: stages are frozen dataclasses dispatched by
# TYPE (no isinstance chain — OCP), composed declaratively from YAML via a pydantic spec. The
# legacy ``TypedPipeline`` (above) is converging onto this engine; both share ``PipelineContext``.
from swarmline.pipeline.dataflow_core import (
    EventSink,
    PipelineError,
    StageConfigError,
    StageDependency,
    StageExecutionError,
    StageOutcome,
    StageValidationError,
    resolve_path,
)
from swarmline.pipeline.dataflow_engine import (
    register_stage_runner,
    run_pipeline,
    stage_runner,
)
from swarmline.pipeline.dataflow_loader import (
    PipelineRegistries,
    build_pipeline,
    load_pipeline_from_yaml,
)
from swarmline.pipeline.stages import (
    ConditionalStage,
    FanOutStage,
    GuardStage,
    LoopStage,
    ParallelStage,
    TypedStage,
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
    "FallbackPolicy",
    "GateResult",
    "Goal",
    "GoalDecomposer",
    "InMemoryPersistentBudgetStore",
    "PersistentBudgetStore",
    "PhaseResult",
    "PhaseStatus",
    "Pipeline",
    "PipelineBuilder",
    "PipelineContext",
    "PipelinePhase",
    "PipelineResult",
    "PipelineRunner",
    "QualityGate",
    "SqlitePersistentBudgetStore",
    "ThresholdAction",
    "ThresholdResult",
    "TypedPipeline",
    "TypedPipelineResult",
    "WorkflowBridge",
    "WorkflowChain",
    "WorkflowChainResult",
    "WorkflowStep",
]

# Typed data-flow pipeline (additive — see import block above).
__all__ += [
    "ConditionalStage",
    "EventSink",
    "FanOutStage",
    "GuardStage",
    "LoopStage",
    "ParallelStage",
    "PipelineError",
    "PipelineRegistries",
    "StageConfigError",
    "StageDependency",
    "StageExecutionError",
    "StageOutcome",
    "StageValidationError",
    "TypedStage",
    "build_pipeline",
    "load_pipeline_from_yaml",
    "register_stage_runner",
    "resolve_path",
    "run_pipeline",
    "stage_runner",
]


def __getattr__(name: str) -> object:
    """PEP 562 — serve the deprecated long stage aliases lazily so ``import swarmline.pipeline`` is clean.

    Delegates to :func:`swarmline.pipeline.typed._warn_deprecated_alias` at the same call depth, so the
    emitted ``DeprecationWarning`` (``stacklevel=3``) points at the user's call site, not at this hook.
    """
    from swarmline.pipeline import typed as _typed

    if name in _typed._DEPRECATED_STAGE_ALIASES:
        return _typed._warn_deprecated_alias(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
