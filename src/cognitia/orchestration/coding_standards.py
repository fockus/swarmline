"""Code pipeline configurations for multi-agent orchestration.

All configs — frozen dataclass (pure value objects, 0 dependencies).
Factory methods provide standard presets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class CodingStandardsConfig:
    """Code standards — all flags are off by default.

    Declaratively sets the mandatory practices for the code task:
    TDD, SOLID, DRY, KISS, Clean Architecture, tests, coverage.
    """

    tdd_enabled: bool = False
    solid_enabled: bool = False
    dry_enabled: bool = False
    kiss_enabled: bool = False
    clean_arch_enabled: bool = False
    integration_tests_required: bool = False
    e2e_tests_required: bool = False
    min_coverage_pct: int = 0

    @classmethod
    def strict(cls) -> CodingStandardsConfig:
        """All checks ON, 95% coverage."""
        return cls(
            tdd_enabled=True,
            solid_enabled=True,
            dry_enabled=True,
            kiss_enabled=True,
            clean_arch_enabled=True,
            integration_tests_required=True,
            e2e_tests_required=True,
            min_coverage_pct=95,
        )

    @classmethod
    def minimal(cls) -> CodingStandardsConfig:
        """Only TDD + basic coverage (70%)."""
        return cls(tdd_enabled=True, min_coverage_pct=70)

    @classmethod
    def off(cls) -> CodingStandardsConfig:
        """All OFF — exploratory mode."""
        return cls()


@dataclass(slots=True, frozen=True)
class WorkflowAutomationConfig:
    """Workflow automation — which pipeline steps are automatic.

    Defines lint, format, test, commit, review automation.
    """

    auto_lint: bool = False
    auto_format: bool = False
    auto_test: bool = False
    auto_commit: bool = False
    auto_review: bool = False

    @classmethod
    def full(cls) -> WorkflowAutomationConfig:
        """All automation ON."""
        return cls(
            auto_lint=True,
            auto_format=True,
            auto_test=True,
            auto_commit=True,
            auto_review=True,
        )

    @classmethod
    def light(cls) -> WorkflowAutomationConfig:
        """Only lint + format + test."""
        return cls(auto_lint=True, auto_format=True, auto_test=True)

    @classmethod
    def off(cls) -> WorkflowAutomationConfig:
        """All automation OFF."""
        return cls()


@dataclass(slots=True, frozen=True)
class AutonomousLoopConfig:
    """Parameters of the autonomous execution cycle by the agent.

    max_cost_credits=0 means "no credit limit".
    """

    max_iterations: int = 10
    max_cost_credits: int = 0
    stop_on_failure: bool = True
    require_approval: bool = True

    @classmethod
    def strict(cls) -> AutonomousLoopConfig:
        """Conservative: low iterations, approval required, stop on failure."""
        return cls(max_iterations=5, stop_on_failure=True, require_approval=True)

    @classmethod
    def light(cls) -> AutonomousLoopConfig:
        """Relaxed: more iterations, no approval, continue on failure."""
        return cls(
            max_iterations=20,
            stop_on_failure=False,
            require_approval=False,
        )


@dataclass(slots=True, frozen=True)
class TeamAgentsConfig:
    """Team agents configuration — which roles are active in the team."""

    use_architect: bool = True
    use_developer: bool = True
    use_tester: bool = True
    use_reviewer: bool = True
    max_parallel_agents: int = 3


@dataclass(slots=True, frozen=True)
class CodePipelineConfig:
    """Code pipeline configuration unit.

    Combines code standards, workflow automation,
    offline loop parameters and team agents.
    """

    standards: CodingStandardsConfig = field(default_factory=CodingStandardsConfig)
    workflow: WorkflowAutomationConfig = field(default_factory=WorkflowAutomationConfig)
    loop: AutonomousLoopConfig = field(default_factory=AutonomousLoopConfig)
    team: TeamAgentsConfig = field(default_factory=TeamAgentsConfig)

    @classmethod
    def production(cls) -> CodePipelineConfig:
        """Production preset: strict standards, full automation, conservative loop."""
        return cls(
            standards=CodingStandardsConfig.strict(),
            workflow=WorkflowAutomationConfig.full(),
            loop=AutonomousLoopConfig.strict(),
        )

    @classmethod
    def development(cls) -> CodePipelineConfig:
        """Development preset: minimal standards, light automation, relaxed loop."""
        return cls(
            standards=CodingStandardsConfig.minimal(),
            workflow=WorkflowAutomationConfig.light(),
            loop=AutonomousLoopConfig.light(),
        )
