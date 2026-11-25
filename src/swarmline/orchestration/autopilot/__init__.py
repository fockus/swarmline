"""Autopilot orchestrator: generative meta-loop (plan -> verify -> deploy -> gate) over the H6 supervisor."""

from __future__ import annotations

from swarmline.orchestration.autopilot.critic import BlueprintCritic, LLMCritic
from swarmline.orchestration.autopilot.deploy_phase import DeployPhase
from swarmline.orchestration.autopilot.engine import OrchestratorEngine
from swarmline.orchestration.autopilot.gate import RoutingContractGate, SubjectiveJudge
from swarmline.orchestration.autopilot.planner import LLMPlanner, Planner
from swarmline.orchestration.autopilot.tools import (
    ORCHESTRATE_TOOL_SPEC,
    create_orchestrate_tool,
)
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    CriticVerdict,
    GateVerdict,
    OrchestrationBlueprint,
    OrchestrationPhase,
    OrchestrationResult,
    OrchestratorConfig,
    OutputContract,
)
from swarmline.orchestration.autopilot.validators import validate_blueprint
from swarmline.orchestration.autopilot.verify_phase import VerifyPhase

__all__ = [
    # Engine + config + result
    "OrchestratorEngine",
    "OrchestratorConfig",
    "OrchestrationResult",
    "OrchestrationPhase",
    # Domain value types
    "OrchestrationBlueprint",
    "BlueprintTask",
    "OutputContract",
    "AcceptanceCriterion",
    "GateVerdict",
    "CriticVerdict",
    # Phase components + their Protocols
    "Planner",
    "LLMPlanner",
    "BlueprintCritic",
    "LLMCritic",
    "VerifyPhase",
    "DeployPhase",
    "RoutingContractGate",
    "SubjectiveJudge",
    "validate_blueprint",
    # Tool surface
    "ORCHESTRATE_TOOL_SPEC",
    "create_orchestrate_tool",
]
