"""Tests for CodingStandardsConfig and related config classes with factory methods."""

from __future__ import annotations

from swarmline.orchestration.coding_standards import (
    AutonomousLoopConfig,
    CodePipelineConfig,
    CodingStandardsConfig,
    TeamAgentsConfig,
    WorkflowAutomationConfig,
)


class TestCodingStandardsConfig:
    def test_strict_all_enabled(self) -> None:
        cfg = CodingStandardsConfig.strict()
        assert cfg.tdd_enabled is True
        assert cfg.solid_enabled is True
        assert cfg.dry_enabled is True
        assert cfg.kiss_enabled is True
        assert cfg.clean_arch_enabled is True
        assert cfg.integration_tests_required is True
        assert cfg.e2e_tests_required is True
        assert cfg.min_coverage_pct == 95

    def test_minimal_only_tdd(self) -> None:
        cfg = CodingStandardsConfig.minimal()
        assert cfg.tdd_enabled is True
        assert cfg.solid_enabled is False
        assert cfg.dry_enabled is False
        assert cfg.kiss_enabled is False
        assert cfg.clean_arch_enabled is False
        assert cfg.integration_tests_required is False
        assert cfg.e2e_tests_required is False
        assert cfg.min_coverage_pct == 70

    def test_off_all_disabled(self) -> None:
        cfg = CodingStandardsConfig.off()
        assert cfg.tdd_enabled is False
        assert cfg.solid_enabled is False
        assert cfg.min_coverage_pct == 0

    def test_default_all_disabled(self) -> None:
        cfg = CodingStandardsConfig()
        assert cfg.tdd_enabled is False
        assert cfg.min_coverage_pct == 0


class TestWorkflowAutomationConfig:
    def test_workflow_full_vs_light(self) -> None:
        full = WorkflowAutomationConfig.full()
        assert full.auto_lint is True
        assert full.auto_format is True
        assert full.auto_test is True
        assert full.auto_commit is True
        assert full.auto_review is True

        light = WorkflowAutomationConfig.light()
        assert light.auto_lint is True
        assert light.auto_format is True
        assert light.auto_test is True
        assert light.auto_commit is False
        assert light.auto_review is False

    def test_workflow_off(self) -> None:
        cfg = WorkflowAutomationConfig.off()
        assert cfg.auto_lint is False
        assert cfg.auto_commit is False


class TestAutonomousLoopConfig:
    def test_strict_conservative(self) -> None:
        cfg = AutonomousLoopConfig.strict()
        assert cfg.max_iterations == 5
        assert cfg.stop_on_failure is True
        assert cfg.require_approval is True

    def test_light_relaxed(self) -> None:
        cfg = AutonomousLoopConfig.light()
        assert cfg.max_iterations == 20
        assert cfg.stop_on_failure is False
        assert cfg.require_approval is False


class TestTeamAgentsConfig:
    def test_defaults_all_roles_active(self) -> None:
        cfg = TeamAgentsConfig()
        assert cfg.use_architect is True
        assert cfg.use_developer is True
        assert cfg.use_tester is True
        assert cfg.use_reviewer is True
        assert cfg.max_parallel_agents == 3


class TestCodePipelineConfig:
    def test_pipeline_config_aggregate(self) -> None:
        cfg = CodePipelineConfig()
        assert isinstance(cfg.standards, CodingStandardsConfig)
        assert isinstance(cfg.workflow, WorkflowAutomationConfig)
        assert isinstance(cfg.loop, AutonomousLoopConfig)
        assert isinstance(cfg.team, TeamAgentsConfig)

    def test_production_preset(self) -> None:
        cfg = CodePipelineConfig.production()
        assert cfg.standards.tdd_enabled is True
        assert cfg.standards.min_coverage_pct == 95
        assert cfg.workflow.auto_lint is True
        assert cfg.workflow.auto_commit is True
        assert cfg.loop.max_iterations == 5
        assert cfg.loop.require_approval is True

    def test_development_preset(self) -> None:
        cfg = CodePipelineConfig.development()
        assert cfg.standards.tdd_enabled is True
        assert cfg.standards.solid_enabled is False
        assert cfg.standards.min_coverage_pct == 70
        assert cfg.workflow.auto_lint is True
        assert cfg.workflow.auto_commit is False
        assert cfg.loop.max_iterations == 20
        assert cfg.loop.require_approval is False
